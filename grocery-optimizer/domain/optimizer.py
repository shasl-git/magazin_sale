"""Алгоритм оптимальной корзины: один магазин + пороги акций + добивка."""

from __future__ import annotations

from collections import defaultdict

from .models import CartLine, CartPlan, Offer, OptimizationResult, Promo


def _pick_cheapest(offers: list[Offer]) -> Offer | None:
    in_stock = [o for o in offers if o.in_stock]
    if not in_stock:
        return None
    return min(in_stock, key=lambda o: (o.price, o.price_per_base))


def _cart_threshold_promos(promos: list[Promo], store: str) -> list[Promo]:
    return [
        p
        for p in promos
        if p.store == store and p.type == "cart_threshold" and p.threshold is not None
    ]


def _free_delivery_promo(promos: list[Promo], store: str) -> Promo | None:
    for p in promos:
        if p.store == store and p.type == "free_delivery":
            return p
    return None


def apply_cart_discount(subtotal: float, promos: list[Promo], store: str) -> tuple[float, list[str], float | None]:
    """Вернуть (скидка, названия акций, сколько не хватает до ближайшего порога)."""
    candidates = _cart_threshold_promos(promos, store)
    if not candidates:
        return 0.0, [], None

    applied_discount = 0.0
    applied_titles: list[str] = []
    shortfall: float | None = None

    # Берём лучшую достижимую акцию; среди недостижимых — ближайший порог
    best_reachable: Promo | None = None
    nearest_miss: Promo | None = None

    for p in sorted(candidates, key=lambda x: x.threshold or 0):
        thr = p.threshold or 0
        if subtotal >= thr:
            best_reachable = p
        elif nearest_miss is None or thr < (nearest_miss.threshold or 0):
            nearest_miss = p

    if best_reachable and best_reachable.discount_value is not None:
        if best_reachable.discount_kind == "percent":
            applied_discount = round(subtotal * best_reachable.discount_value, 2)
        else:
            applied_discount = min(subtotal, best_reachable.discount_value)
        applied_titles.append(best_reachable.title)
    elif nearest_miss and nearest_miss.threshold is not None:
        shortfall = round(nearest_miss.threshold - subtotal, 2)

    return applied_discount, applied_titles, shortfall


def apply_delivery(
    subtotal_before_cart_discount: float,
    promos: list[Promo],
    store: str,
    delivery_cost: float,
) -> tuple[float, list[str]]:
    """Доставка с учётом free_delivery. Порог — от суммы до корзинной скидки."""
    fd = _free_delivery_promo(promos, store)
    titles: list[str] = []
    if fd and fd.threshold is not None and subtotal_before_cart_discount >= fd.threshold:
        titles.append(fd.title)
        return 0.0, titles
    return delivery_cost, titles


def build_store_plan(
    store: str,
    needs: list[str],
    offers_by_need: dict[str, list[Offer]],
    promos: list[Promo],
    delivery_cost: float,
    selected: dict[str, Offer] | None = None,
    counts: dict[str, int] | None = None,
) -> CartPlan | None:
    """Собрать корзину в одном магазине. selected — уже выбранные SKU."""
    selected = selected or {}
    lines: list[CartLine] = []

    for need in needs:
        if need in selected and selected[need].store == store:
            offer = selected[need]
        else:
            store_offers = [o for o in offers_by_need.get(need, []) if o.store == store]
            offer = _pick_cheapest(store_offers)
        if offer is None:
            return None  # магазин не покрывает весь список
        lines.append(CartLine(need=need, offer=offer, count=_count_of(counts, need)))

    subtotal = round(sum(line.offer.price * line.count for line in lines), 2)
    discount, promo_titles, shortfall = apply_cart_discount(subtotal, promos, store)
    after = round(subtotal - discount, 2)
    delivery, delivery_titles = apply_delivery(subtotal, promos, store, delivery_cost)
    total = round(after + delivery, 2)

    return CartPlan(
        store=store,
        lines=lines,
        subtotal=subtotal,
        discount=discount,
        delivery=delivery,
        total=total,
        applied_promos=promo_titles + delivery_titles,
        shortfall_to_threshold=shortfall,
    )


def optimize_cart(
    needs: list[str],
    offers: list[Offer],
    promos: list[Promo],
    *,
    delivery_cost: float = 500.0,
    single_store_only: bool = True,
    selected: dict[str, Offer] | None = None,
    stores: list[str] | None = None,
    counts: dict[str, int] | None = None,
) -> OptimizationResult:
    """
    Построить планы по магазинам и выбрать лучший по final_price.

    single_store_only=True — не смешиваем магазины (режим пользователя).
    """
    needs = [n.strip().lower() for n in needs if n.strip()]
    offers_by_need: dict[str, list[Offer]] = defaultdict(list)
    for o in offers:
        if o.in_stock:
            offers_by_need[o.need.lower()].append(o)

    store_names = stores or sorted({o.store for o in offers})
    plans: list[CartPlan] = []
    for store in store_names:
        plan = build_store_plan(
            store,
            needs,
            offers_by_need,
            promos,
            delivery_cost,
            selected=selected,
            counts=counts,
        )
        if plan is not None:
            plans.append(plan)

    plans.sort(key=lambda p: (p.total, p.subtotal))

    # База: обычные цены выбранных SKU, иначе самая дешёвая полка без порогов.
    baseline = _baseline_total(
        needs,
        offers_by_need,
        delivery_cost,
        store_names,
        selected=selected,
        counts=counts,
    )

    # На MVP single_store_only: планы уже только по одному магазину
    _ = single_store_only

    return OptimizationResult(plans=plans, baseline_total=baseline)


def _baseline_total(
    needs: list[str],
    offers_by_need: dict[str, list[Offer]],
    delivery_cost: float,
    stores: list[str],
    selected: dict[str, Offer] | None = None,
    counts: dict[str, int] | None = None,
) -> float:
    """«В лоб»: обычная цена выбранных SKU, иначе мин. полка, без порогов + доставка."""
    if selected and all(need in selected for need in needs):
        total = 0.0
        for need in needs:
            offer = selected[need]
            unit = offer.old_price if offer.old_price else offer.price
            total += unit * _count_of(counts, need)
        return round(total + delivery_cost, 2)
    best = None
    for store in stores:
        total = 0.0
        ok = True
        for need in needs:
            store_offers = [o for o in offers_by_need.get(need, []) if o.store == store]
            pick = _pick_cheapest(store_offers)
            if pick is None:
                ok = False
                break
            # Берём old_price если есть — «обычная» цена без оптимизации
            unit = pick.old_price if pick.old_price else pick.price
            total += unit * _count_of(counts, need)
        if ok:
            candidate = round(total + delivery_cost, 2)
            if best is None or candidate < best:
                best = candidate
    return best if best is not None else 0.0


def _count_of(counts: dict[str, int] | None, need: str) -> int:
    if not counts:
        return 1
    try:
        value = int(counts.get(need, 1))
    except (TypeError, ValueError):
        return 1
    return value if value >= 1 else 1


def compare_sku(offers: list[Offer], *, limit: int = 4) -> list[tuple[Offer, str]]:
    """
    Сравнить варианты одной нужды: цена за базовую единицу.
    Возвращает (offer, подпись выгоды).
    """
    stocked = [o for o in offers if o.in_stock]
    if not stocked:
        return []

    ranked = sorted(stocked, key=lambda o: (o.price_per_base, o.price))[:limit]
    best_ppb = ranked[0].price_per_base
    result: list[tuple[Offer, str]] = []

    for i, o in enumerate(ranked):
        if i == 0:
            note = "самый выгодный за единицу"
        else:
            diff = o.price_per_base - best_ppb
            # Пересчёт «на литр / на кг» если единица мл/г
            if o.unit in ("мл", "л"):
                per_liter = diff * (1000 if o.unit == "мл" else 1)
                note = f"дороже на ~{per_liter:.1f} ₽/л"
            elif o.unit in ("г", "кг"):
                per_kg = diff * (1000 if o.unit == "г" else 1)
                note = f"дороже на ~{per_kg:.1f} ₽/кг"
            else:
                note = f"дороже на {diff:.3f} ₽/{o.unit}"
        result.append((o, note))
    return result


def suggest_topup(
    plan: CartPlan,
    catalog: list[Offer],
    *,
    max_suggestions: int = 3,
) -> list[Offer]:
    """
    Если не хватает до порога — предложить дешёвые товары того же магазина,
    которыми можно добить (не дороже shortfall * 1.5).
    """
    if plan.shortfall_to_threshold is None or plan.shortfall_to_threshold <= 0:
        return []

    need_ids = {line.offer.external_id for line in plan.lines}
    shortfall = plan.shortfall_to_threshold
    candidates = [
        o
        for o in catalog
        if o.store == plan.store
        and o.in_stock
        and o.external_id not in need_ids
        and shortfall <= o.price <= shortfall * 1.5
    ]
    candidates.sort(key=lambda o: abs(o.price - shortfall))
    return candidates[:max_suggestions]
