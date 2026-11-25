"""Доменные модели: офферы, акции, планы корзины."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

PromoType = Literal["item_discount", "cart_threshold", "n_plus_m", "free_delivery"]
DiscountKind = Literal["percent", "amount"]
Unit = Literal["мл", "г", "шт", "л", "кг"]


@dataclass(frozen=True)
class Offer:
    store: str  # magnit | pyaterochka | samokat
    need: str  # «молоко» — что искал пользователь
    external_id: str
    title: str
    price: float
    old_price: float | None = None
    unit: str = "шт"
    qty: float = 1.0
    url: str = ""
    in_stock: bool = True

    @property
    def price_per_base(self) -> float:
        """Цена за базовую единицу (мл / г / шт)."""
        if self.qty <= 0:
            return self.price
        return self.price / self.qty


@dataclass(frozen=True)
class Promo:
    store: str
    type: PromoType
    title: str
    threshold: float | None = None
    discount_value: float | None = None
    discount_kind: DiscountKind | None = None


@dataclass
class CartLine:
    need: str
    offer: Offer
    count: int = 1


@dataclass
class CartPlan:
    store: str
    lines: list[CartLine]
    subtotal: float  # сумма до корзинной акции
    discount: float  # скидка от cart_threshold
    delivery: float
    total: float  # к оплате
    applied_promos: list[str] = field(default_factory=list)
    shortfall_to_threshold: float | None = None  # сколько не хватает до порога

    @property
    def item_count(self) -> int:
        return len(self.lines)


@dataclass
class OptimizationResult:
    plans: list[CartPlan]  # лучший первым, потом альтернативы
    baseline_total: float  # «в лоб» без оптимизатора
    best: CartPlan | None = None

    def __post_init__(self) -> None:
        if self.best is None and self.plans:
            self.best = self.plans[0]

    @property
    def savings_vs_baseline(self) -> float:
        if not self.best:
            return 0.0
        return max(0.0, round(self.baseline_total - self.best.total, 2))
