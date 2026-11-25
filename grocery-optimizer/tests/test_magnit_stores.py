"""Офлайн-тесты моделей магазина Магнита (без сети)."""

from parsers.magnit_stores import MagnitStore, _is_grocery_point, _is_grocery_summary


def test_distance_industrial_to_self_is_zero():
    s = MagnitStore("1", "x", "STORE_TYPE_MM", 53.347, 83.670)
    assert s.distance_km(53.347, 83.670) < 0.01


def test_filters_out_pharmacy_and_cosmetic():
    assert not _is_grocery_summary(
        {
            "storeType": "STORE_TYPE_DISTR_PHARMACY",
            "externalId": {"storeCode": "123"},
        }
    )
    assert not _is_grocery_summary(
        {
            "storeType": "STORE_TYPE_MC",
            "externalId": {"storeCode": "123"},
        }
    )
    assert _is_grocery_summary(
        {
            "storeType": "STORE_TYPE_MM",
            "externalId": {"storeCode": "489493"},
        }
    )


def test_shop_by_point_skips_type_3():
    assert not _is_grocery_point({"xml_id": "1", "store_type": 3, "active": True})
    assert _is_grocery_point({"xml_id": "489493", "store_type": 1, "active": True})
