"""Интерфейс в терминале.

Живые цены Магнита (по умолчанию):
  python cli.py "молоко, хлеб, сахар, чипсы, кола"

Выбор SKU и запись покупки:
  python cli.py --choose "молоко, хлеб"
  python cli.py --sku "2,1" --bought "молоко, хлеб"
  python cli.py --again
  python cli.py --delivery 0 "молоко, хлеб"
  python cli.py --stats

Фейковый каталог двух магазинов (алгоритм, без сети):
  python cli.py --fake "молоко, хлеб"
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import time

from bot.screens import STORE_TITLE, screen_final, screen_saved, screen_stats
from config import DB_PATH, STORES, USER
from data.fake_catalog import FAKE_OFFERS, FAKE_PROMOS
from db import init_db
from db.aliases import load_preferred, save_preferred
from db.manual_promos import load_manual_promos
from db.purchases import last_live_items, load_entries, plan_breakdown, save_purchase
from domain.matching import parse_items, parse_list
from domain.models import Offer, OptimizationResult, Promo
from domain.optimizer import compare_sku, optimize_cart, suggest_topup
from domain.savings import record_purchase, saved_since_midnight, summarize
from domain.selection import (
    SKU_SHOW,
    PickError,
    overlay_preferred,
    parse_sku_spec,
    pick_offers,
    ranked_choices,
)
from parsers.magnit import MagnitApiError, MagnitNetworkError, MagnitParser
from parsers.magnit_promos import fetch_first_order_promo


_YES = {"y", "yes", "д", "да"}


def _best_per_unit(offers: list[Offer]) -> dict[str, Offer]:
    """Для живого Магнита в план берём выгодный за мл/г/шт, не самую дешёвую пачку."""
    selected: dict[str, Offer] = {}
    by_need: dict[str, list[Offer]] = {}
    for offer in offers:
        if offer.in_stock:
            by_need.setdefault(offer.need, []).append(offer)
    for need, variants in by_need.items():
        ranked = compare_sku(variants, limit=len(variants))
        if ranked:
            selected[need] = ranked[0][0]
    return selected


def format_plan(
    result,
    offers: list[Offer],
    *,
    source_note: str,
    show_topup: bool,
    promo_notes: list[str] | None = None,
    hint: bool = True,
    delivery_cost: float = USER.delivery_cost_default,
    preface: str | None = None,
) -> str:
    lines: list[str] = []
    if preface:
        lines.append(preface)
    if result.best:
        lines.append(f"🛒 Список: {_fmt_items([(line.need, line.count) for line in result.best.lines])}")
    lines.append(f"📍 {USER.city}, {USER.district}")
    lines.append(f"🚚 Доставка, если порог не взят: {delivery_cost:.0f} ₽ · один магазин")
    lines.append(f"Источник: {source_note}")
    if promo_notes:
        lines.append("")
        lines.append("🔥 Акции Магнита")
        lines.extend(promo_notes)
    lines.append("")

    if not result.plans:
        lines.append("Не удалось собрать корзину: не у всех позиций есть товар в наличии.")
        for need in dict.fromkeys(o.need for o in offers):
            variants = [o for o in offers if o.need == need and o.in_stock]
            ranked = compare_sku(variants, limit=SKU_SHOW)
            if not ranked:
                lines.append(f"• {need}: нет в наличии")
                continue
            top = ranked[0][0]
            lines.append(f"• {need}: {top.title} — {top.price:.0f} ₽")
        return "\n".join(lines)

    best = result.best
    assert best is not None
    lines.append("🔥 Рекомендация")
    lines.append(
        f"👉 {STORE_TITLE.get(best.store, best.store)}: "
        f"до акций {best.subtotal:.0f} ₽ → к оплате {best.total:.0f} ₽"
    )
    if best.discount:
        lines.append(f"   скидка корзины: −{best.discount:.0f} ₽")
    lines.append(f"   доставка: {best.delivery:.0f} ₽")
    if best.applied_promos:
        lines.append(f"   акции: {'; '.join(best.applied_promos)}")
    lines.append(f"   база без оптимизатора: {result.baseline_total:.0f} ₽")
    lines.append(f"   экономия: ≈ {result.savings_vs_baseline:.0f} ₽")
    lines.append("")

    lines.append(f"📦 План ({STORE_TITLE.get(best.store, best.store)})")
    for line in best.lines:
        lines.append(f"• {_line_text(line)}  ({line.offer.price_per_base:.3f} ₽/{line.offer.unit})")
    lines.append(f"Итого до акций: {best.subtotal:.0f} ₽")
    lines.append(f"К оплате: {best.total:.0f} ₽")
    lines.append("")

    if len(result.plans) > 1:
        lines.append("Альтернативы:")
        for alt in result.plans[1:]:
            worse = alt.total - best.total
            lines.append(
                f"• {STORE_TITLE.get(alt.store, alt.store)} — {alt.total:.0f} ₽ "
                f"(хуже на {worse:.0f} ₽)"
            )
        lines.append("")

    if best.shortfall_to_threshold and show_topup:
        lines.append(f"⚠️ До порога акции не хватает {best.shortfall_to_threshold:.0f} ₽")
        tips = suggest_topup(best, offers)
        if tips:
            for tip in tips:
                lines.append(f"   • {tip.title} — {tip.price:.0f} ₽")
        else:
            lines.append("   Допиши товар в список, если хочешь добрать до порога.")
        lines.append("")
    elif best.shortfall_to_threshold:
        lines.append(f"⚠️ До порога акции не хватает {best.shortfall_to_threshold:.0f} ₽")
        lines.append("")

    shown: set[str] = set()
    for line in best.lines:
        if line.need in shown:
            continue
        shown.add(line.need)
        variants = [o for o in offers if o.need == line.need and o.store == best.store]
        ranked = compare_sku(variants, limit=SKU_SHOW)
        if not ranked:
            continue
        lines.append(f"🥛 {line.need.capitalize()} — варианты в {STORE_TITLE.get(best.store)}:")
        for i, (offer, note) in enumerate(ranked, 1):
            mark = "✅" if offer.external_id == line.offer.external_id else "  "
            was = f", было {offer.old_price:.0f}" if offer.old_price else ""
            lines.append(
                f"{mark} {i}. {offer.title} — {offer.price:.0f} ₽{was} "
                f"({offer.price_per_base:.4f} ₽/{offer.unit}) — {note}"
            )
        hidden = sum(1 for o in variants if o.in_stock) - len(ranked)
        if hidden > 0:
            lines.append(f"   … ещё {hidden}, в выборе первые {len(ranked)}")
        lines.append("")

    if hint and result.best:
        lines.append('Дальше: --choose    или    --sku "2,1"    и    --bought')
        lines.append("История: --stats")

    return "\n".join(lines)


def _load_magnit(
    needs: list[str], *, shelf: bool
) -> tuple[list[Offer], list[str], str]:
    if not STORES.magnit_store_code:
        raise RuntimeError(
            "Нет shopCode Магнита. Сначала:\n  python -m tools.find_stores"
        )
    init_db(DB_PATH)
    found: list[Offer] = []
    missing: list[str] = []
    from_cache = 0
    parser_kwargs = {"catalog_type": "1", "store_type": "1"} if shelf else {}
    with MagnitParser(STORES.magnit_store_code, **parser_kwargs) as parser, sqlite3.connect(DB_PATH) as conn:
        mode = parser.catalog_mode
        for index, need in enumerate(needs):
            offers, cached = parser.search_cached(conn, need)
            if cached:
                from_cache += 1
            else:
                conn.commit()
                if index + 1 < len(needs):
                    time.sleep(0.4)
            if not any(o.in_stock for o in offers):
                missing.append(need)
            found.extend(offers)
    label = "полка магазина" if shelf else "каталог доставки"
    note = (
        f"Магнит shopCode={STORES.magnit_store_code}, {label} ({mode}), "
        f"запросов из кэша {from_cache}/{len(needs)}. "
        "Скидка с ценника уже в цене."
    )
    return found, missing, note


def _collect_promos(first_order: bool) -> tuple[list[Promo], list[str]]:
    banner = fetch_first_order_promo()
    with sqlite3.connect(DB_PATH) as conn:
        manual = load_manual_promos(conn, STORES.magnit_store_code)
    applied = list(manual)
    notes = [f"• {promo.title}" for promo in manual]
    if banner is None:
        notes.append("• Баннер первого заказа на главной не прочитался.")
    elif first_order:
        applied.append(banner)
        notes.append(
            f"• {banner.title} — в расчёте, если корзина от {banner.threshold:.0f} ₽"
        )
    else:
        notes.append(
            f"• {banner.title} — не в сумме. "
            "Добавь --first-order, если это первый заказ доставки."
        )
    if not manual:
        notes.append("• Постоянный порог: python -m tools.set_promo --help")
    return applied, notes


def _magnit_preferred() -> dict[tuple[str, str], str]:
    init_db(DB_PATH)
    with sqlite3.connect(DB_PATH) as conn:
        return load_preferred(conn, "magnit")


def _ask_picks(needs: list[str], ranked, current: dict[str, Offer], input_fn) -> dict[str, int]:
    print("")
    print("Выбор SKU. Enter — оставить отмеченное ✅.")
    indexes: dict[str, int] = {}
    for need in needs:
        options = ranked.get(need) or []
        if len(options) <= 1:
            title = options[0][0].title if options else "нет в наличии"
            print(f"• {need}: {title}")
            continue
        current_offer = current.get(need)
        hint = ""
        if current_offer is not None:
            for number, (offer, _) in enumerate(options, 1):
                if offer.external_id == current_offer.external_id:
                    hint = f", сейчас {number}"
                    break
        while True:
            raw = input_fn(f"  {need} — номер 1..{len(options)}{hint}: ").strip()
            if raw == "":
                break
            if raw.isdigit() and 1 <= int(raw) <= len(options):
                indexes[need] = int(raw)
                break
            print(f"  Нужен номер от 1 до {len(options)} или Enter.")
    return indexes


def _fmt_items(items: list[tuple[str, int]]) -> str:
    return ", ".join(name if count == 1 else f"{name} ×{count}" for name, count in items)


def _line_text(line) -> str:
    if line.count > 1:
        total = line.offer.price * line.count
        return f"{line.offer.title} — {line.offer.price:.0f} ₽ ×{line.count} = {total:.0f} ₽"
    return f"{line.offer.title} — {line.offer.price:.0f} ₽"


def _ask_delivery(current: float, input_fn) -> float:
    while True:
        raw = input_fn(f"Доставка, ₽ (Enter = {current:.0f}): ").strip().replace(",", ".")
        if raw == "":
            return current
        try:
            value = float(raw)
        except ValueError:
            print("  Введите число или Enter.")
            continue
        if value < 0:
            print("  Доставка не может быть отрицательной.")
            continue
        return value


def _ask_paid(default: float, input_fn) -> float:
    while True:
        raw = input_fn(f"Оплатил, ₽ (Enter = {default:.0f}): ").strip().replace(",", ".")
        if raw == "":
            return default
        try:
            value = float(raw)
        except ValueError:
            print("  Введите число или Enter.")
            continue
        if value < 0:
            print("  Сумма не может быть отрицательной.")
            continue
        return value


def _record(result: OptimizationResult, paid: float | None, *, source: str = "live") -> None:
    best = result.best
    assert best is not None
    entry = record_purchase(
        baseline_total=result.baseline_total,
        calculated_total=best.total,
        paid_total=paid,
        store=best.store,
    )
    init_db(DB_PATH)
    with sqlite3.connect(DB_PATH) as conn:
        save_purchase(conn, entry, plan_breakdown(best, source=source))
        if source != "fake":
            save_preferred(conn, best.lines)
        entries = load_entries(conn)
    print("")
    if source == "fake":
        print("Это --fake: в общий счёт и в запомненные SKU не входит.")
        return
    summary = summarize(entries)
    print(
        screen_saved(
            saved_since_midnight(entries),
            summary.month,
            summary.half_year,
            summary.year,
        )
    )


def _print_stats() -> int:
    init_db(DB_PATH)
    with sqlite3.connect(DB_PATH) as conn:
        entries = load_entries(conn)
    summary = summarize(entries)
    recent = [
        f"• {entry.bought_at:%d.%m} {STORE_TITLE.get(entry.store, entry.store)} "
        f"— экономия {entry.saved:.0f} ₽"
        for entry in summary.entries[:5]
    ]
    print(screen_stats(summary.week, summary.month, summary.half_year, summary.year, recent))
    return 0


def _print_final(result: OptimizationResult) -> None:
    best = result.best
    assert best is not None
    items = [f"• {_line_text(line)}" for line in best.lines]
    print("")
    print(
        screen_final(
            best.store,
            items,
            best.subtotal,
            best.discount,
            best.delivery,
            best.total,
            result.baseline_total,
            result.savings_vs_baseline,
        )
    )


def _shopping_list(args) -> tuple[list[tuple[str, int]], str | None]:
    """Позиции на этот запуск и строка «повтор», если список взят из прошлой покупки."""
    extra = parse_items(args.list) if args.list is not None else []
    if not args.again:
        if args.list is None:
            return [(name, 1) for name in parse_list(", ".join(USER.sample_list))], None
        return extra, None

    init_db(DB_PATH)
    with sqlite3.connect(DB_PATH) as conn:
        last = last_live_items(conn)
    if last is None:
        raise PickError("Живых покупок ещё нет. Сначала список и --bought.")
    bought_at, base = last
    items = list(base)
    have = {name for name, _count in items}
    added: list[tuple[str, int]] = []
    for name, count in extra:
        if name in have:
            continue
        items.append((name, count))
        added.append((name, count))
    note = f"Повтор закупки от {bought_at:%d.%m.%Y}: {_fmt_items(base)}"
    if added:
        note += f" + {_fmt_items(added)}"
    return items, note


def main(argv: list[str] | None = None, *, input_fn=None, assume_tty: bool | None = None) -> int:
    parser = argparse.ArgumentParser(description="Оптимизатор покупок: живой Магнит или --fake")
    parser.add_argument(
        "list",
        nargs="?",
        default=None,
        help='Список через запятую, например: "молоко, хлеб, сахар"',
    )
    parser.add_argument(
        "--fake",
        action="store_true",
        help="Фейковые цены Магнита и Пятёрочки, без сети",
    )
    parser.add_argument(
        "--first-order",
        action="store_true",
        help="Учесть скидку первого заказа с баннера magnit.ru",
    )
    parser.add_argument(
        "--shelf",
        action="store_true",
        help="Цены полки магазина, а не каталога доставки",
    )
    parser.add_argument(
        "--sku",
        default=None,
        help='Номера вариантов: "2,1" или "молоко=2". «-» — оставить рекомендацию',
    )
    parser.add_argument(
        "--choose",
        action="store_true",
        help="Спросить номер SKU в терминале",
    )
    parser.add_argument(
        "--bought",
        action="store_true",
        help="Записать покупку и экономию",
    )
    parser.add_argument(
        "--paid",
        type=float,
        default=None,
        help="Сколько оплатил, ₽. Само включает запись покупки",
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="Сколько уже сэкономлено",
    )
    parser.add_argument(
        "--again",
        action="store_true",
        help="Повторить последнюю живую закупку. Список в аргументе — добавить позиции",
    )
    parser.add_argument(
        "--delivery",
        type=float,
        default=None,
        help="Доставка на этот запуск, ₽. 0 — самовывоз или уже бесплатно",
    )
    parser.add_argument(
        "--plan",
        action="store_true",
        help="Только напечатать план, без вопросов в терминале",
    )
    args = parser.parse_args(argv)
    reader = input_fn or input

    if args.sku and args.choose:
        print("Укажи либо --sku, либо --choose.")
        return 1
    if args.plan and args.choose:
        print("Укажи либо --plan, либо --choose.")
        return 1
    if args.paid is not None and args.paid < 0:
        print("Сумма не может быть отрицательной.")
        return 1
    if args.delivery is not None and args.delivery < 0:
        print("Доставка не может быть отрицательной.")
        return 1

    wants_cart = any(
        (
            args.list is not None,
            args.fake,
            args.choose,
            args.sku is not None,
            args.bought,
            args.paid is not None,
            args.shelf,
            args.first_order,
            args.again,
            args.delivery is not None,
            args.plan,
        )
    )
    if args.stats and not wants_cart:
        return _print_stats()

    try:
        items, again_note = _shopping_list(args)
    except PickError as exc:
        print(exc)
        return 1
    if not items:
        print("Пустой список.")
        return 1
    needs = [name for name, _count in items]
    counts = {name: count for name, count in items}
    delivery_cost = USER.delivery_cost_default if args.delivery is None else args.delivery
    tty = sys.stdin.isatty() if assume_tty is None else assume_tty
    interactive = (not args.plan) and args.sku is None and (
        args.choose or (tty and not args.bought and args.paid is None)
    )

    if args.fake:
        offers: list[Offer] = list(FAKE_OFFERS)
        promos: list[Promo] = FAKE_PROMOS
        source = "фейковый каталог (Магнит + Пятёрочка)"
        selected: dict[str, Offer] = {}
        show_topup = True
        missing: list[str] = []
        promo_notes: list[str] = []
    else:
        try:
            offers, missing, source = _load_magnit(needs, shelf=args.shelf)
            promos, promo_notes = _collect_promos(args.first_order)
        except (MagnitNetworkError, MagnitApiError, RuntimeError) as exc:
            print(exc)
            return 2
        selected = overlay_preferred(offers, _best_per_unit(offers), _magnit_preferred())
        show_topup = any(p.type == "cart_threshold" for p in promos)

    result = optimize_cart(
        needs,
        offers,
        promos,
        delivery_cost=delivery_cost,
        single_store_only=USER.single_store_only,
        selected=selected or None,
        counts=counts,
    )

    if interactive or args.sku is not None:
        if result.best is None:
            print(
                format_plan(
                    result,
                    offers,
                    source_note=source,
                    show_topup=show_topup,
                    promo_notes=promo_notes,
                    hint=False,
                    delivery_cost=delivery_cost,
                    preface=again_note,
                )
            )
            print("Нечего выбирать: корзина не собралась.")
            return 1
        store = result.best.store
        ranked = ranked_choices(offers, needs, store)
        try:
            if args.sku is not None:
                indexes = parse_sku_spec(args.sku, needs)
            else:
                if input_fn is None and not tty:
                    print('Интерактивный выбор нужен в терминале. Для скрипта: --sku "2,1" --plan')
                    return 1
                print(
                    format_plan(
                        result,
                        offers,
                        source_note=source,
                        show_topup=show_topup,
                        promo_notes=promo_notes,
                        hint=False,
                        delivery_cost=delivery_cost,
                        preface=again_note,
                    )
                )
                current = {line.need: line.offer for line in result.best.lines}
                indexes = _ask_picks(needs, ranked, current, reader)
            picked = pick_offers(ranked, indexes)
        except PickError as exc:
            print(exc)
            return 1
        if interactive and args.delivery is None:
            delivery_cost = _ask_delivery(delivery_cost, reader)
        selected.update(picked)
        result = optimize_cart(
            needs,
            offers,
            promos,
            delivery_cost=delivery_cost,
            single_store_only=USER.single_store_only,
            selected=selected or None,
            stores=[store],
            counts=counts,
        )

    if interactive and result.best is not None:
        _print_final(result)
    else:
        print(
            format_plan(
                result,
                offers,
                source_note=source,
                show_topup=show_topup,
                promo_notes=promo_notes,
                hint=not args.stats,
                delivery_cost=delivery_cost,
                preface=again_note,
            )
        )
    if missing:
        print("Не найдено в наличии: " + ", ".join(missing))
    if result.best is None:
        return 1

    record = args.bought or args.paid is not None
    paid = args.paid
    if interactive and not record:
        answer = reader("Записать «я купил»? [д/н]: ").strip().lower()
        record = answer in _YES
    if record and interactive and paid is None:
        paid = _ask_paid(result.best.total, reader)
    if record:
        _record(result, paid, source="fake" if args.fake else "live")
    if args.stats:
        _print_stats()
    return 0


if __name__ == "__main__":
    sys.exit(main())
