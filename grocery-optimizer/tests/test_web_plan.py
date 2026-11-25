"""Локальный сайт: демо-план, смена SKU, доставка, демо-покупка не пишется."""

from __future__ import annotations

import pytest

from web.service import (
    PlanError,
    load_meta,
    merge_shelf_and_delivery,
    promo_progress,
    recalculate,
    record_purchase_from_session,
    start_plan,
)
from domain.models import Offer


def test_demo_starts_with_the_best_unit():
    payload = start_plan("кола", fake=True, delivery=0)
    selected = next(item for item in payload["choices"]["кола"] if item["selected"])
    assert selected["note"].startswith("самый выгодный")
    keys = [gap["key"] for gap in load_meta()["gaps"]]
    assert keys == ["prices", "promos", "stores"]
    assert [store["id"] for store in load_meta()["stores"]] == ["084788"]


def test_site_total_is_goods_only():
    payload = start_plan("молоко", fake=True)
    assert payload["plan"]["delivery"] == 0
    assert payload["plan"]["total"] == round(
        payload["plan"]["subtotal"] - payload["plan"]["discount"], 2
    )
    assert any(item["old_price"] and item["old_price"] > item["price"] for item in payload["choices"]["молоко"])


def test_shelf_price_stays_and_delivery_is_attached_only_when_both_exist():
    shelf = Offer("magnit", "яйца", "1", "Яйца 10 шт", 80, 100, "шт", 10)
    delivery = Offer("magnit", "яйца", "1", "Яйца 10 шт", 95, None, "шт", 10)
    only_delivery = Offer("magnit", "яйца", "2", "Яйца 20", 150, None, "шт", 20)
    offers, prices = merge_shelf_and_delivery([shelf], [delivery, only_delivery])
    assert prices == {"1": 95.0}
    assert [offer.external_id for offer in offers] == ["1", "2"]
    assert offers[0].old_price == 100
    assert offers[0].price == 80


def test_promo_discount_waits_until_the_threshold():
    promo = {"threshold": 800, "discount_kind": "percent", "discount_value": 0.25}
    early = promo_progress(80, promo)
    assert early["applied"] is False
    assert early["shortfall"] == 720
    done = promo_progress(800, promo)
    assert done["applied"] is True
    assert done["discount"] == 200
    assert done["total"] == 600


def test_demo_plan_switches_sku_delivery_and_count():
    payload = start_plan("молоко, хлеб", fake=True, delivery=200)
    assert payload["plan"]["store"] in {"magnit", "pyaterochka"}
    assert payload["fake"] is True
    milk_options = payload["choices"]["молоко"]
    assert len(milk_options) > 1
    other = next(item for item in milk_options if not item["selected"])

    picked = recalculate(payload["token"], picks={"молоко": other["external_id"]})
    milk = next(line for line in picked["plan"]["lines"] if line["need"] == "молоко")
    assert milk["external_id"] == other["external_id"]

    delivered = recalculate(payload["token"], delivery=77)
    assert delivered["plan"]["delivery"] == 77

    counted = recalculate(payload["token"], counts={"молоко": 3})
    milk = next(line for line in counted["plan"]["lines"] if line["need"] == "молоко")
    assert milk["count"] == 3
    assert "молоко x3" in counted["list_text"]


def test_demo_purchase_is_not_saved():
    payload = start_plan("молоко", fake=True)
    result = record_purchase_from_session(payload["token"], paid=10)
    assert result["saved"] is False


def test_empty_list_and_negative_delivery():
    with pytest.raises(PlanError):
        start_plan("  ")
    with pytest.raises(PlanError):
        start_plan("молоко", fake=True, delivery=-5)


def test_chosen_promo_waits_until_the_manual_cart_reaches_it():
    promo = {
        "title": "от 800",
        "threshold": 800,
        "discount_value": 0.25,
        "discount_kind": "percent",
    }
    payload = start_plan("молоко", fake=True, manual=True, promo=promo)
    assert payload["plan"]["lines"] == []
    assert payload["plan"]["shortfall"] == 800
    sku = payload["choices"]["молоко"][0]["external_id"]
    picked = recalculate(payload["token"], picks={"молоко": sku}, promo=promo, replace_promo=True)
    price = picked["plan"]["lines"][0]["price"]
    assert picked["plan"]["discount"] == 0
    assert picked["plan"]["shortfall"] == round(800 - price, 2)


def test_manual_cart_stays_empty_until_a_product_is_chosen():
    payload = start_plan("молоко", fake=True, manual=True)
    assert payload["plan"]["lines"] == []
    assert all(not item["selected"] for item in payload["choices"]["молоко"])
    sku = payload["choices"]["молоко"][0]["external_id"]
    picked = recalculate(payload["token"], picks={"молоко": sku})
    assert [line["external_id"] for line in picked["plan"]["lines"]] == [sku]
    cleared = recalculate(payload["token"], picks={"молоко": ""})
    assert cleared["plan"]["lines"] == []


def test_missing_session():
    with pytest.raises(PlanError) as caught:
        recalculate("missing")
    assert caught.value.status == 404
