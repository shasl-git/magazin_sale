"""Юнит-тесты алгоритма на синтетических данных."""

from __future__ import annotations

from domain.models import Offer, Promo
from domain.optimizer import (
    apply_cart_discount,
    compare_sku,
    optimize_cart,
    suggest_topup,
)
from domain.savings import compute_saved, record_purchase, summarize
from datetime import datetime, timedelta


def _offers() -> list[Offer]:
    return [
        Offer("magnit", "молоко", "1", "Молоко A 1л", 100, 120, "мл", 1000),
        Offer("magnit", "хлеб", "2", "Хлеб", 50, 60, "г", 500),
        Offer("magnit", "яйца", "3", "Яйца", 90, 100, "шт", 10),
        Offer("pyaterochka", "молоко", "4", "Молоко B 1л", 95, 115, "мл", 1000),
        Offer("pyaterochka", "хлеб", "5", "Хлеб", 55, 65, "г", 500),
        Offer("pyaterochka", "яйца", "6", "Яйца", 88, 98, "шт", 10),
        # добивка
        Offer("magnit", "добивка", "7", "Печенье", 80, 90, "г", 200),
    ]


def _promos() -> list[Promo]:
    return [
        Promo(
            "magnit",
            "cart_threshold",
            "−20% от 200",
            threshold=200,
            discount_value=0.20,
            discount_kind="percent",
        ),
        Promo("magnit", "free_delivery", "0 доставка от 200", threshold=200),
        Promo(
            "pyaterochka",
            "cart_threshold",
            "−50 от 300",
            threshold=300,
            discount_value=50,
            discount_kind="amount",
        ),
    ]


def test_magnit_hits_threshold_and_beats_pyaterochka():
    result = optimize_cart(
        ["молоко", "хлеб", "яйца"],
        _offers(),
        _promos(),
        delivery_cost=500,
        single_store_only=True,
    )
    assert result.best is not None
    assert result.best.store == "magnit"
    # 100+50+90 = 240 → −20% = 48 → 192 + доставка 0 = 192
    assert result.best.subtotal == 240
    assert result.best.discount == 48
    assert result.best.delivery == 0
    assert result.best.total == 192
    assert result.savings_vs_baseline > 0


def test_shortfall_when_under_threshold():
    offers = [
        Offer("magnit", "молоко", "1", "Молоко", 80, None, "мл", 1000),
        Offer("magnit", "хлеб", "2", "Хлеб", 40, None, "г", 500),
    ]
    promos = [
        Promo(
            "magnit",
            "cart_threshold",
            "−20% от 200",
            threshold=200,
            discount_value=0.20,
            discount_kind="percent",
        )
    ]
    result = optimize_cart(["молоко", "хлеб"], offers, promos, delivery_cost=100)
    assert result.best is not None
    assert result.best.discount == 0
    assert result.best.shortfall_to_threshold == 80


def test_apply_cart_discount_amount():
    promos = [
        Promo(
            "pyaterochka",
            "cart_threshold",
            "−300",
            threshold=1500,
            discount_value=300,
            discount_kind="amount",
        )
    ]
    discount, titles, shortfall = apply_cart_discount(1600, promos, "pyaterochka")
    assert discount == 300
    assert shortfall is None
    assert titles


def test_compare_sku_ranks_by_unit_price():
    offers = [
        Offer("magnit", "молоко", "a", "1 л за 100", 100, None, "мл", 1000),
        Offer("magnit", "молоко", "b", "1.2 л за 110", 110, None, "мл", 1200),
        Offer("magnit", "молоко", "c", "0.9 л за 95", 95, None, "мл", 900),
    ]
    ranked = compare_sku(offers)
    assert ranked[0][0].external_id == "b"  # 110/1200 ≈ 0.0917 — лучше
    assert "выгодный" in ranked[0][1]


def test_suggest_topup():
    result = optimize_cart(
        ["молоко", "хлеб"],
        [
            Offer("magnit", "молоко", "1", "Молоко", 80, None, "мл", 1000),
            Offer("magnit", "хлеб", "2", "Хлеб", 40, None, "г", 500),
            Offer("magnit", "добивка", "3", "Печенье", 85, None, "г", 200),
        ],
        [
            Promo(
                "magnit",
                "cart_threshold",
                "от 200",
                threshold=200,
                discount_value=0.1,
                discount_kind="percent",
            )
        ],
        delivery_cost=0,
    )
    tips = suggest_topup(result.best, [
        Offer("magnit", "молоко", "1", "Молоко", 80, None, "мл", 1000),
        Offer("magnit", "хлеб", "2", "Хлеб", 40, None, "г", 500),
        Offer("magnit", "добивка", "3", "Печенье", 85, None, "г", 200),
    ])
    assert tips
    assert tips[0].external_id == "3"


def test_baseline_follows_selected_sku_old_price():
    cheap = Offer("magnit", "молоко", "cheap", "Маленькое 200мл", 40, None, "мл", 200)
    good = Offer("magnit", "молоко", "good", "1 л", 100, 130, "мл", 1000)
    result = optimize_cart(
        ["молоко"],
        [cheap, good],
        [],
        delivery_cost=500,
        selected={"молоко": good},
    )
    assert result.best is not None
    assert result.best.subtotal == 100
    assert result.baseline_total == 630
    assert result.savings_vs_baseline == 30


def test_count_doubles_price_and_baseline():
    offer = Offer("magnit", "молоко", "1", "Молоко", 100, 130, "мл", 1000)
    result = optimize_cart(
        ["молоко"],
        [offer],
        [],
        delivery_cost=0,
        counts={"молоко": 2},
    )
    assert result.best is not None
    assert result.best.lines[0].count == 2
    assert result.best.subtotal == 200
    assert result.baseline_total == 260


def test_savings():
    assert compute_saved(1000, 800) == 200
    e = record_purchase(
        baseline_total=1000,
        calculated_total=800,
        paid_total=820,
        store="magnit",
        bought_at=datetime.now() - timedelta(days=2),
    )
    assert e.saved == 180
    s = summarize([e])
    assert s.week == 180
    assert s.month == 180
