"""Баннер первого заказа и ручные акции — без сети."""

import sqlite3

from db import init_db
from db.manual_promos import load_manual_promos, replace_manual_promo
from domain.models import Promo
from domain.optimizer import optimize_cart
from domain.models import Offer
from parsers.magnit_promos import parse_first_order_banner


BANNER = """
<div>Скидка 35% на первый заказ</div>
<span>От 1000₽ по промокоду</span>
<div>БЕРИ35</div>
"""


def test_parse_first_order_banner():
    promo = parse_first_order_banner(BANNER)
    assert promo is not None
    assert promo.type == "cart_threshold"
    assert promo.threshold == 1000
    assert promo.discount_kind == "percent"
    assert promo.discount_value == 0.35
    assert "БЕРИ35" in promo.title
    assert "первый заказ" in promo.title


def test_parse_ignores_page_without_banner():
    assert parse_first_order_banner("<html>просто каталог</html>") is None


def test_manual_promo_replaces_same_type_and_applies(tmp_path):
    db = init_db(tmp_path / "app.db")
    offer = Offer("magnit", "молоко", "1", "Молоко 1 л", 1200, 1200, "мл", 1000)
    with sqlite3.connect(db) as conn:
        replace_manual_promo(
            conn,
            "084788",
            Promo("magnit", "cart_threshold", "−20% от 1000", 1000, 0.2, "percent"),
        )
        replace_manual_promo(
            conn,
            "084788",
            Promo("magnit", "cart_threshold", "−10% от 1000", 1000, 0.1, "percent"),
        )
        replace_manual_promo(
            conn,
            "084788",
            Promo("magnit", "free_delivery", "0 от 1000", 1000),
        )
        promos = load_manual_promos(conn, "084788")
    assert len(promos) == 2
    result = optimize_cart(["молоко"], [offer], promos, delivery_cost=500)
    assert result.best is not None
    assert result.best.discount == 120
    assert result.best.delivery == 0
    assert result.best.total == 1080
