"""Разбор ответа каталога Магнита и кэш — без сети."""

from datetime import datetime, timedelta, timezone

from db.offers_cache import load_offers, save_offers
from db import init_db
from domain.models import Offer
from parsers.magnit import goods_to_offer, kopecks_to_rub, parse_pack


def test_pack_from_name_normalizes_to_ml_and_g():
    assert parse_pack("Молоко 1 л") == ("мл", 1000)
    assert parse_pack("Молоко 1,2л") == ("мл", 1200)
    assert parse_pack("Кола 0.5 л") == ("мл", 500)
    assert parse_pack("Сахар песок 1 кг") == ("г", 1000)
    assert parse_pack("Чипсы 140г") == ("г", 140)
    assert parse_pack("Чокопай 6 шт") == ("шт", 6)
    assert parse_pack("Сок 6х200 мл") == ("мл", 1200)


def test_weighted_shelf_overrides_name():
    assert parse_pack("Бананы", shelf_weight=1400, is_weighted=True) == ("г", 1400)


def test_kopecks_and_rubles():
    assert kopecks_to_rub(16999) == 169.99
    assert kopecks_to_rub(169.99) == 169.99
    assert kopecks_to_rub(None) is None


def test_goods_item_promo_and_url():
    offer = goods_to_offer(
        {
            "id": "8000034165",
            "productId": "8000034165",
            "name": "Молоко Простоквашино 2.5% 970мл",
            "price": 16999,
            "promotion": {"isPromotion": True, "oldPrice": 19999},
            "quantity": 18,
            "seoCode": "prostokvashino_moloko",
            "weighted": {"isWeighted": False},
        },
        "молоко",
        "489493",
    )
    assert offer is not None
    assert offer.price == 169.99
    assert offer.old_price == 199.99
    assert offer.unit == "мл"
    assert offer.qty == 970
    assert offer.in_stock is True
    assert "shopCode=489493" in offer.url
    assert offer.need == "молоко"


def test_card_flag_without_old_price_is_not_discount():
    offer = goods_to_offer(
        {
            "id": "1",
            "name": "Хлеб дарницкий 650г",
            "price": 4500,
            "promotion": {"isPromotion": True, "oldPrice": None},
            "quantity": 4,
        },
        "хлеб",
        "1",
    )
    assert offer is not None
    assert offer.price == 45.0
    assert offer.old_price is None
    assert offer.unit == "г"
    assert offer.qty == 650


def test_zero_quantity_is_out_of_stock():
    offer = goods_to_offer(
        {"id": "9", "name": "Сахар 1 кг", "price": 7900, "quantity": 0},
        "сахар",
        "1",
    )
    assert offer is not None
    assert offer.in_stock is False


def test_cache_roundtrip_and_expiry(tmp_path):
    db = init_db(tmp_path / "app.db")
    import sqlite3

    offer = Offer("magnit", "молоко", "42", "Молоко 1 л", 90.0, 110.0, "мл", 1000)
    now = datetime(2026, 11, 23, 12, 0, tzinfo=timezone.utc)
    with sqlite3.connect(db) as conn:
        save_offers(conn, [offer], need="молоко", store_code="111", scraped_at=now)
        fresh = load_offers(
            conn, need="молоко", store_code="111", max_age_hours=3, now=now + timedelta(hours=1)
        )
        stale = load_offers(
            conn, need="молоко", store_code="111", max_age_hours=3, now=now + timedelta(hours=4)
        )
        other = load_offers(conn, need="хлеб", store_code="111", now=now)
    assert fresh is not None and len(fresh) == 1
    assert fresh[0].price == 90.0
    assert fresh[0].old_price == 110.0
    assert fresh[0].price_per_base == 0.09
    assert stale is None
    assert other is None
