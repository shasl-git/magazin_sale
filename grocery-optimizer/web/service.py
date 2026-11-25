"""Сборка плана для сайта: те же цены, акции и оптимизатор, что в CLI."""

from __future__ import annotations

import secrets
import sqlite3
import threading
import time
from dataclasses import dataclass, field

from config import DB_PATH, STORES, USER
from data.fake_catalog import FAKE_OFFERS, FAKE_PROMOS
from db import init_db
from db.aliases import load_preferred, save_preferred
from db.manual_promos import load_manual_promos
from db.purchases import last_live_items, load_entries, plan_breakdown, save_purchase
from domain.matching import parse_items
from domain.models import Offer, OptimizationResult, Promo
from domain.optimizer import optimize_cart, suggest_topup
from domain.savings import record_purchase, summarize
from domain.selection import SKU_SHOW, ranked_choices
from parsers.magnit import MagnitParser
from parsers.magnit_promos import fetch_first_order_promo
from parsers.magnit_stores import find_stores, find_stores_near

STORE_TITLE = {
    "magnit": "Магнит",
    "pyaterochka": "Пятёрочка",
    "samokat": "Самокат",
}


class PlanError(Exception):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


@dataclass
class PlanSession:
    token: str
    items: list[tuple[str, int]]
    offers: list[Offer]
    promos: list[Promo]
    source_note: str
    missing: list[str]
    promo_notes: list[str]
    fake: bool
    picks: dict[str, str] = field(default_factory=dict)
    delivery: float = 0.0
    store: str | None = None
    again_note: str | None = None
    shop_code: str = ""
    delivery_prices: dict[str, float] = field(default_factory=dict)
    manual: bool = False


_sessions: dict[str, PlanSession] = {}


def load_meta() -> dict:
    return {
        "city": USER.city,
        "district": USER.district,
        "store_code": STORES.magnit_store_code,
        "store_title": "Магнит",
        "sample_list": ", ".join(USER.sample_list),
        "stores": [_home_shop()],
        "gaps": _static_gaps(),
    }


def load_stats() -> dict:
    init_db(DB_PATH)
    with sqlite3.connect(DB_PATH) as conn:
        entries = load_entries(conn)
        last = last_live_items(conn)
    summary = summarize(entries)
    return {
        "week": summary.week,
        "month": summary.month,
        "half_year": summary.half_year,
        "year": summary.year,
        "recent": [
            {
                "date": entry.bought_at.strftime("%d.%m"),
                "store": STORE_TITLE.get(entry.store, entry.store),
                "saved": entry.saved,
                "paid": entry.paid_total,
            }
            for entry in summary.entries[:6]
        ],
        "last_list": None
        if last is None
        else {
            "date": last[0].strftime("%d.%m.%Y"),
            "text": ", ".join(
                name if count == 1 else f"{name} x{count}" for name, count in last[1]
            ),
        },
    }


def start_plan(
    text: str | None,
    *,
    fake: bool = False,
    shelf: bool = False,
    first_order: bool = False,
    delivery: float | None = None,
    again: bool = False,
    picks: dict[str, str] | None = None,
    shop_code: str | None = None,
    manual: bool = False,
    promo: dict | None = None,
    progress=None,
) -> dict:
    code = _shop_code(shop_code)
    items, again_note = _items_for(text, again=again)
    delivery_cost = 0.0 if delivery is None else _delivery(delivery)
    delivery_prices: dict[str, float] = {}
    if fake:
        offers = list(FAKE_OFFERS)
        promos = list(FAKE_PROMOS)
        missing: list[str] = []
        source = "Демонстрационные цены Магнита и Пятёрочки, без сети"
        promo_notes = [promo.title for promo in promos]
        preferred: dict[tuple[str, str], str] = {}
        if manual:
            promos = _chosen_promo(promo)
            promo_notes = _manual_promo_notes(promos)
        if progress is not None:
            progress(1, 1, "Готово")
    else:
        try:
            offers, delivery_prices, missing, source = _load_both(
                needs_of(items), code, progress=progress
            )
            if manual:
                promos = _chosen_promo(promo)
                promo_notes = _manual_promo_notes(promos)
            else:
                promos, promo_notes = _shop_promos(code)
        except Exception as exc:
            raise PlanError(str(exc), status=502) from exc
        preferred = _preferred()
    session = PlanSession(
        token=secrets.token_hex(8),
        items=items,
        offers=offers,
        promos=promos,
        source_note=source,
        missing=missing,
        promo_notes=promo_notes,
        fake=fake,
        delivery=delivery_cost,
        again_note=again_note,
        shop_code=code,
        delivery_prices=delivery_prices,
        manual=manual,
    )
    _sessions[session.token] = session
    payload, _result = _publish(
        session, preferred=preferred, picks=picks or {}, first_order=first_order
    )
    return payload


def recalculate(
    token: str,
    *,
    picks: dict[str, str] | None = None,
    delivery: float | None = None,
    counts: dict[str, int] | None = None,
    store: str | None = None,
    promo: dict | None = None,
    replace_promo: bool = False,
) -> dict:
    session = _sessions.get(token)
    if session is None:
        raise PlanError("План устарел. Собери его ещё раз.", status=404)
    if delivery is not None:
        session.delivery = _delivery(delivery)
    if counts:
        session.items = [
            (name, _bounded(counts.get(name, count))) for name, count in session.items
        ]
    if store:
        session.store = store
        session.picks = {
            need: sku
            for need, sku in session.picks.items()
            if any(
                offer.external_id == sku and offer.store == store
                for offer in session.offers
            )
        }
    if replace_promo and session.manual:
        session.promos = _chosen_promo(promo)
        session.promo_notes = _manual_promo_notes(session.promos)
    if picks and not store:
        picked_stores = {
            offer.store
            for need, sku in picks.items()
            if (offer := _find(session.offers, str(need), str(sku), store=None)) is not None
        }
        if len(picked_stores) == 1:
            session.store = next(iter(picked_stores))
    payload, _result = _publish(session, preferred={}, picks=picks or {})
    return payload


def record_purchase_from_session(
    token: str,
    *,
    paid: float | None = None,
    picks: dict[str, str] | None = None,
    delivery: float | None = None,
) -> dict:
    session = _sessions.get(token)
    if session is None:
        raise PlanError("План устарел. Собери его ещё раз.", status=404)
    payload, result = _publish(
        session, preferred={}, picks=picks or {}, delivery=delivery
    )
    if result.best is None or not result.best.lines:
        raise PlanError("Сначала выбери товары.")
    if session.fake:
        return {
            "saved": False,
            "message": "Это демо-цены. В общий счёт и в запомненные товары они не пишутся.",
            **payload,
        }
    paid_total = result.best.total if paid is None else _money(paid, "Сумма")
    entry = record_purchase(
        baseline_total=result.baseline_total,
        calculated_total=result.best.total,
        paid_total=paid_total,
        store=result.best.store,
    )
    init_db(DB_PATH)
    with sqlite3.connect(DB_PATH) as conn:
        save_purchase(conn, entry, plan_breakdown(result.best, source="live"))
        save_preferred(conn, result.best.lines)
    return {
        "saved": True,
        "message": f"Записал. Экономия этой покупки {entry.saved:.0f} ₽.",
        "saved_now": entry.saved,
        "stats": load_stats(),
        **payload,
    }


def _publish(
    session: PlanSession,
    *,
    preferred: dict[tuple[str, str], str],
    picks: dict[str, str],
    delivery: float | None = None,
    first_order: bool = False,
) -> tuple[dict, OptimizationResult]:
    if delivery is not None:
        session.delivery = _delivery(delivery)
    if picks:
        for need, sku in picks.items():
            key = str(need)
            if sku:
                session.picks[key] = str(sku)
            else:
                session.picks.pop(key, None)
    needs = [
        name
        for name, _count in session.items
        if not session.manual or name in session.picks
    ]
    counts = {name: count for name, count in session.items}
    stores = [session.store] if session.store else _stores_of(session.offers)
    built: list[OptimizationResult] = []
    for store in stores:
        selected = _selection_for_store(
            session, store, {} if session.manual else preferred
        )
        result = optimize_cart(
            needs,
            session.offers,
            session.promos,
            delivery_cost=session.delivery,
            single_store_only=USER.single_store_only,
            selected=selected or None,
            stores=[store],
            counts=counts,
        )
        if result.best is not None:
            built.append(result)
    built.sort(key=lambda item: (item.best.total, item.best.subtotal))  # type: ignore[union-attr]
    if built:
        result = built[0]
        result.plans = [item.best for item in built if item.best is not None]
    else:
        result = optimize_cart(
            needs,
            session.offers,
            session.promos,
            delivery_cost=session.delivery,
            counts=counts,
        )
    if result.best is not None and not session.manual:
        session.picks = {
            line.need: line.offer.external_id for line in result.best.lines
        }
    store = result.best.store if result.best is not None else _fallback_store(session.offers)
    return _payload(session, result, store, first_order=first_order), result


def _payload(
    session: PlanSession,
    result: OptimizationResult,
    store: str,
    *,
    first_order: bool,
) -> dict:
    best = result.best
    topup: list[dict] = []
    if best is not None and best.shortfall_to_threshold:
        topup = [_offer_brief(offer) for offer in suggest_topup(best, session.offers)]
    alternatives = []
    if best is not None:
        for plan in result.plans:
            if plan.store == best.store:
                continue
            alternatives.append(
                {
                    "store": plan.store,
                    "store_title": STORE_TITLE.get(plan.store, plan.store),
                    "total": plan.total,
                    "worse_by": round(plan.total - best.total, 2),
                }
            )
    return {
        "token": session.token,
        "fake": session.fake,
        "again_note": session.again_note,
        "source_note": session.source_note,
        "missing": session.missing,
        "promo_notes": session.promo_notes,
        "list_text": ", ".join(
            name if count == 1 else f"{name} x{count}" for name, count in session.items
        ),
        "delivery": session.delivery,
        "active_promo": _promo_brief(session.promos),
        "gaps": _plan_gaps(session, result, first_order=first_order),
        "plan": None
        if best is None
        else {
            "store": best.store,
            "store_title": STORE_TITLE.get(best.store, best.store),
            "subtotal": best.subtotal,
            "discount": best.discount,
            "delivery": best.delivery,
            "total": best.total,
            "baseline": result.baseline_total,
            "savings": result.savings_vs_baseline,
            "applied_promos": list(best.applied_promos),
            "shortfall": best.shortfall_to_threshold,
            "topup": topup,
            "lines": [
                {
                    "need": line.need,
                    "count": line.count,
                    "external_id": line.offer.external_id,
                    "title": line.offer.title,
                    "price": line.offer.price,
                    "old_price": line.offer.old_price,
                    "unit": line.offer.unit,
                    "qty": line.offer.qty,
                    "line_total": round(line.offer.price * line.count, 2),
                    "delivery_price": session.delivery_prices.get(line.offer.external_id),
                    "url": line.offer.url,
                }
                for line in best.lines
            ],
            "alternatives": alternatives,
        },
        "choices": _choices(
            session.offers,
            [name for name, _ in session.items],
            store,
            session.picks,
            session.delivery_prices,
        ),
    }


def _choices(
    offers: list[Offer],
    needs: list[str],
    store: str,
    picks: dict[str, str],
    delivery_prices: dict[str, float] | None = None,
) -> dict[str, list[dict]]:
    prices = delivery_prices or {}
    ranked = ranked_choices(offers, needs, store, limit=SKU_SHOW)
    choices: dict[str, list[dict]] = {}
    for need in needs:
        options = []
        for offer, note in ranked.get(need, []):
            brief = _attach_delivery(_offer_brief(offer), offer, prices)
            brief["note"] = note
            brief["selected"] = picks.get(need) == offer.external_id
            options.append(brief)
        if not options:
            options = [
                _attach_delivery(
                    {
                        **_offer_brief(offer),
                        "note": "нет в выбранном магазине" if not offer.in_stock else "",
                        "selected": False,
                    },
                    offer,
                    prices,
                )
                for offer in offers
                if offer.need == need and offer.store == store
            ][:SKU_SHOW]
        choices[need] = options
    return choices


def _attach_delivery(brief: dict, offer: Offer, prices: dict[str, float]) -> dict:
    value = prices.get(offer.external_id)
    if value is not None:
        brief["delivery_price"] = value
    return brief


def _offer_brief(offer: Offer) -> dict:
    return {
        "external_id": offer.external_id,
        "store": offer.store,
        "title": offer.title,
        "price": offer.price,
        "old_price": offer.old_price,
        "unit": offer.unit,
        "qty": offer.qty,
        "price_per_base": round(offer.price_per_base, 6),
        "in_stock": offer.in_stock,
        "url": offer.url,
    }


def _selection_for_store(
    session: PlanSession,
    store: str,
    preferred: dict[tuple[str, str], str],
) -> dict[str, Offer]:
    """В каждом магазине сначала выгодный товар за единицу, потом память и клик."""
    needs = [name for name, _count in session.items]
    if session.manual:
        selected: dict[str, Offer] = {}
        for need, sku in session.picks.items():
            match = _find(session.offers, need, sku, store=store)
            if match is not None:
                selected[need] = match
        return selected
    selected = {
        need: options[0][0]
        for need, options in ranked_choices(session.offers, needs, store, limit=1).items()
        if options
    }
    for (need, pref_store), sku in preferred.items():
        if pref_store != store:
            continue
        match = _find(session.offers, need, sku, store=store)
        if match is not None:
            selected[need] = match
    for need, sku in session.picks.items():
        match = _find(session.offers, need, sku, store=store)
        if match is not None:
            selected[need] = match
    return selected


def _stores_of(offers: list[Offer]) -> list[str]:
    found = {offer.store for offer in offers if offer.in_stock}
    return [name for name in ("magnit", "pyaterochka", "samokat") if name in found]


def _find(
    offers: list[Offer],
    need: str,
    sku: str,
    *,
    store: str | None,
) -> Offer | None:
    for offer in offers:
        if offer.need != need or offer.external_id != sku or not offer.in_stock:
            continue
        if store is not None and offer.store != store:
            continue
        return offer
    return None


def _items_for(text: str | None, *, again: bool) -> tuple[list[tuple[str, int]], str | None]:
    extra = parse_items(text) if text and text.strip() else []
    if not again:
        if not extra:
            raise PlanError("Напиши список: молоко, хлеб, сахар.")
        return extra, None
    init_db(DB_PATH)
    with sqlite3.connect(DB_PATH) as conn:
        last = last_live_items(conn)
    if last is None:
        raise PlanError("Живых покупок ещё нет. Сначала собери план и нажми «Я купил».")
    bought_at, base = last
    items = list(base)
    have = {name for name, _count in items}
    added = [(name, count) for name, count in extra if name not in have]
    items.extend(added)
    note = f"Повтор закупки от {bought_at:%d.%m.%Y}"
    return items, note


def _preferred() -> dict[tuple[str, str], str]:
    init_db(DB_PATH)
    with sqlite3.connect(DB_PATH) as conn:
        return load_preferred(conn, "magnit")


def _fallback_store(offers: list[Offer]) -> str:
    for name in ("magnit", "pyaterochka", "samokat"):
        if any(offer.store == name for offer in offers):
            return name
    return "magnit"


def _store_choices() -> list[dict]:
    return [_home_shop()]


def _home_shop() -> dict:
    return {
        "id": STORES.magnit_store_code,
        "title": "Магнит",
        "address": "ул. 280-летия Барнаула, зд. 17",
        "ready": True,
    }


def list_shop_points(query: str = "") -> dict:
    """Адреса Магнита. Пустой запрос — точки рядом с районом, иначе поиск по тексту."""
    key = " ".join(query.strip().lower().split())
    now = time.time()
    cached = _SHOP_CACHE.get(key)
    if cached is not None and now - cached[0] < 6 * 3600:
        return {"stores": cached[1], "error": None}
    try:
        if key:
            text = query.strip()
            city = USER.city.split(",")[0].strip()
            if city and city.lower() not in text.lower():
                text = f"{city} {text}"
            found = find_stores(text, prefer_near=False, limit=12)
        else:
            found = find_stores_near(limit=12)
    except Exception as exc:
        return {"stores": [_home_shop()], "error": str(exc)}
    stores = [
        {
            "id": shop.store_code,
            "title": shop.type_label,
            "address": shop.address,
            "ready": True,
        }
        for shop in found
        if shop.store_code and shop.address
    ]
    if not any(shop["id"] == STORES.magnit_store_code for shop in stores):
        stores.append(_home_shop())
    if not stores:
        stores = [_home_shop()]
    _SHOP_CACHE[key] = (now, stores)
    return {"stores": stores, "error": None}


def merge_shelf_and_delivery(
    shelf: list[Offer],
    delivery: list[Offer],
) -> tuple[list[Offer], dict[str, float]]:
    """Полка остаётся основной ценой. Рядом можно показать цену доставки того же SKU."""
    delivery_by_id = {offer.external_id: offer for offer in delivery}
    prices: dict[str, float] = {}
    seen: set[str] = set()
    merged: list[Offer] = []
    for offer in shelf:
        if offer.external_id in seen:
            continue
        seen.add(offer.external_id)
        other = delivery_by_id.get(offer.external_id)
        if other is not None:
            prices[offer.external_id] = other.price
        merged.append(offer)
    for offer in delivery:
        if offer.external_id in seen:
            continue
        seen.add(offer.external_id)
        merged.append(offer)
    return merged, prices


def promo_progress(subtotal: float, promo: dict) -> dict:
    """Скидка порога включается только когда сумма товаров его достигла."""
    threshold = float(promo["threshold"])
    kind = promo.get("discount_kind") or "percent"
    value = float(promo["discount_value"])
    if subtotal + 0.001 < threshold:
        return {
            "applied": False,
            "shortfall": round(threshold - subtotal, 2),
            "discount": 0.0,
            "total": round(subtotal, 2),
        }
    if kind == "percent":
        discount = round(subtotal * value, 2)
    else:
        discount = round(min(subtotal, value), 2)
    return {
        "applied": True,
        "shortfall": 0.0,
        "discount": discount,
        "total": round(subtotal - discount, 2),
    }


def list_visible_promos(shop_code: str | None = None) -> dict:
    code = _shop_code(shop_code)
    init_db(DB_PATH)
    with sqlite3.connect(DB_PATH) as conn:
        manual = load_manual_promos(conn, code)
    banner = fetch_first_order_promo()
    promos = list(manual)
    if banner is not None:
        promos.append(banner)
    visible: list[dict] = []
    note = (
        "Порог корзины: баннер первого заказа с главной и акции, сохранённые командой set_promo. "
        "Скидка на ценнике остаётся на карточке товара, сюда она не дублируется."
    )
    for index, promo in enumerate(promos):
        if promo.type != "cart_threshold" or not promo.threshold or not promo.discount_value:
            continue
        visible.append(
            {
                "id": f"{index}:{promo.title}",
                "title": promo.title,
                "threshold": promo.threshold,
                "discount_value": promo.discount_value,
                "discount_kind": promo.discount_kind or "percent",
            }
        )
    return {"promos": visible, "note": note}


def search_promo_products(shop_code: str | None, text: str) -> list[dict]:
    code = _shop_code(shop_code)
    items = parse_items(text or "")
    if not items:
        raise PlanError("Напиши, что искать.")
    offers, prices, _missing, _source = _load_both(needs_of(items), code)
    found: list[dict] = []
    for need, _count in items:
        for offer, note in ranked_choices(offers, [need], "magnit", limit=SKU_SHOW).get(need, []):
            brief = _offer_brief(offer)
            brief["need"] = need
            brief["note"] = note
            _attach_delivery(brief, offer, prices)
            found.append(brief)
    return found


_SHOP_CACHE: dict[str, tuple[float, list[dict]]] = {}


def _shop_code(value: str | None) -> str:
    code = (value or "").strip()
    if not code or code in {"magnit", "pyaterochka", "samokat"}:
        if not STORES.magnit_store_code:
            raise PlanError("Нет точки Магнита. Сначала: python -m tools.find_stores")
        return STORES.magnit_store_code
    if not code.isdigit():
        raise PlanError("Нужен код точки Магнита.")
    return code


def needs_of(items: list[tuple[str, int]]) -> list[str]:
    return [name for name, _count in items]


def _load_both(
    needs: list[str],
    store_code: str,
    progress=None,
) -> tuple[list[Offer], dict[str, float], list[str], str]:
    total = max(len(needs) * 2, 1)
    done = 0

    def tick(label: str) -> None:
        nonlocal done
        done += 1
        if progress is not None:
            progress(min(done, total), total, label)

    shelf, shelf_missing, shelf_cached = _load_catalog(
        needs, store_code, shelf=True, tick=lambda need: tick(f"Полка: {need}")
    )
    delivery, _delivery_missing, delivery_cached = _load_catalog(
        needs, store_code, shelf=False, tick=lambda need: tick(f"Онлайн: {need}")
    )
    offers, prices = merge_shelf_and_delivery(shelf, delivery)
    missing = [
        need
        for need in needs
        if not any(offer.need == need and offer.in_stock for offer in offers)
    ]
    if not shelf and not missing:
        missing = shelf_missing
    note = (
        f"Магнит {store_code}: полка из кэша {shelf_cached}/{len(needs)}, "
        f"онлайн из кэша {delivery_cached}/{len(needs)}. "
        "Крупная цена — полка, оранжевая — онлайн."
    )
    return offers, prices, missing, note


def _load_catalog(
    needs: list[str], store_code: str, *, shelf: bool, tick=None
) -> tuple[list[Offer], list[str], int]:
    init_db(DB_PATH)
    parser_kwargs = {"catalog_type": "1", "store_type": "1"} if shelf else {}
    found: list[Offer] = []
    missing: list[str] = []
    from_cache = 0
    with MagnitParser(store_code, **parser_kwargs) as parser, sqlite3.connect(DB_PATH) as conn:
        for index, need in enumerate(needs):
            offers, cached = parser.search_cached(conn, need)
            if cached:
                from_cache += 1
            else:
                conn.commit()
                if index + 1 < len(needs):
                    time.sleep(0.4)
            if not any(offer.in_stock for offer in offers):
                missing.append(need)
            found.extend(offers)
            if tick is not None:
                tick(need)
    return found, missing, from_cache


def _chosen_promo(data: dict | None) -> list[Promo]:
    if not isinstance(data, dict):
        return []
    try:
        threshold = float(data["threshold"])
        value = float(data["discount_value"])
    except (TypeError, ValueError, KeyError):
        return []
    kind = data.get("discount_kind") or "percent"
    if kind not in {"percent", "amount"}:
        kind = "percent"
    title = str(data.get("title") or "Акция")
    return [Promo("magnit", "cart_threshold", title, threshold, value, kind)]


def _manual_promo_notes(promos: list[Promo]) -> list[str]:
    if promos:
        return [promo.title for promo in promos]
    return ["Акция выбирается на странице «Акции». Скидка на ценнике видна у товара."]


def _promo_brief(promos: list[Promo]) -> dict | None:
    promo = next((item for item in promos if item.type == "cart_threshold"), None)
    if promo is None:
        return None
    return {
        "title": promo.title,
        "threshold": promo.threshold,
        "discount_value": promo.discount_value,
        "discount_kind": promo.discount_kind or "percent",
    }


_JOBS: dict[str, dict] = {}


def queue_plan(
    text: str | None,
    *,
    shop_code: str | None = None,
    manual: bool = False,
    promo: dict | None = None,
) -> str:
    job_id = secrets.token_hex(8)
    state = {
        "current": 0,
        "total": 1,
        "label": "Ищу цены…",
        "done": False,
        "payload": None,
        "error": None,
    }
    _JOBS[job_id] = state

    def progress(current: int, total: int, label: str) -> None:
        state["current"] = current
        state["total"] = max(int(total), 1)
        state["label"] = label

    def run() -> None:
        try:
            state["payload"] = start_plan(
                text,
                shop_code=shop_code,
                manual=manual,
                promo=promo,
                progress=progress,
            )
        except PlanError as exc:
            state["error"] = str(exc)
        except Exception as exc:
            state["error"] = str(exc)
        finally:
            state["done"] = True
            state["current"] = state["total"]

    threading.Thread(target=run, daemon=True).start()
    return job_id


def read_plan_job(job_id: str) -> dict:
    state = _JOBS.get(job_id)
    if state is None:
        raise PlanError("Загрузка не найдена.", status=404)
    data = {
        "done": state["done"],
        "current": state["current"],
        "total": state["total"],
        "label": state["label"],
    }
    if state["done"]:
        if state["error"]:
            data["error"] = state["error"]
        else:
            data["payload"] = state["payload"]
    return data


def _shop_promos(store_code: str) -> tuple[list[Promo], list[str]]:
    init_db(DB_PATH)
    with sqlite3.connect(DB_PATH) as conn:
        manual = load_manual_promos(conn, store_code)
    if manual:
        return manual, [promo.title for promo in manual]
    return [], ["Порог корзины выбирается на странице «Акции». Скидка на ценнике уже в цене полки."]


def _stores_gap() -> dict:
    return {
        "key": "stores",
        "title": "Магазины",
        "state": "later",
        "detail": "Список — это адреса Магнита. Цены считаются в выбранной точке.",
    }


def _static_gaps() -> list[dict]:
    return [
        {
            "key": "prices",
            "title": "Цены Магнита",
            "state": "ready",
            "detail": "Крупная цена — полка. Оранжевым меньше написан онлайн. Старая цена зачёркнута, текущая полка — зелёная.",
        },
        {
            "key": "promos",
            "title": "Акции",
            "state": "partial",
            "detail": "Скидка на ценнике видна у товара. Порог корзины и «2+1» сами с сайта не читаются.",
        },
        _stores_gap(),
    ]


def _plan_gaps(
    session: PlanSession,
    result: OptimizationResult,
    *,
    first_order: bool,
) -> list[dict]:
    if session.fake:
        prices = {
            "key": "prices",
            "title": "Цены",
            "state": "demo",
            "detail": "Это не Магнит. Цены вымышленные, чтобы видеть алгоритм без сети.",
        }
        stores = {
            "key": "stores",
            "title": "Другие сети",
            "state": "demo",
            "detail": "В демо Пятёрочка считается. В живом режиме её ещё нет.",
        }
    elif session.missing:
        prices = {
            "key": "prices",
            "title": "Цены Магнита",
            "state": "partial",
            "detail": "Нет в наличии: " + ", ".join(session.missing) + ".",
        }
        stores = _stores_gap()
    else:
        prices = {
            "key": "prices",
            "title": "Цены Магнита",
            "state": "ready",
            "detail": session.source_note,
        }
        stores = _stores_gap()

    promo_detail = " · ".join(session.promo_notes) if session.promo_notes else _static_gaps()[1]["detail"]
    if session.fake:
        promo_state = "demo"
    elif first_order or any(promo.type == "cart_threshold" for promo in session.promos):
        promo_state = "partial"
    else:
        promo_state = "partial"
    promos = {
        "key": "promos",
        "title": "Акции",
        "state": promo_state,
        "detail": promo_detail,
    }

    return [prices, promos, stores]


def _delivery(value: float) -> float:
    return _money(value, "Доставка")


def _money(value: float, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise PlanError(f"{label}: нужно число.") from exc
    if number < 0:
        raise PlanError(f"{label} не может быть отрицательной.")
    return number


def _bounded(value: object) -> int:
    try:
        number = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 1
    return min(30, max(1, number))
