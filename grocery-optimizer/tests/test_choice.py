"""Выбор SKU, запись «я купил» и подстановка запомненного товара."""

from __future__ import annotations

import sqlite3

from db import init_db
from db.aliases import load_preferred, save_preferred
from db.purchases import load_entries, plan_breakdown, save_purchase
from domain.models import CartLine, Offer
from domain.optimizer import optimize_cart
from domain.savings import record_purchase, saved_since_midnight, summarize
from domain.selection import PickError, overlay_preferred, parse_sku_spec, pick_offers, ranked_choices
from datetime import datetime, timedelta

import pytest

from cli import main


def test_parse_sku_positional_and_named():
    needs = ["молоко", "хлеб", "сахар"]
    assert parse_sku_spec("2, -, 1", needs) == {"молоко": 2, "сахар": 1}
    assert parse_sku_spec("Молоко=2, хлеб=0", needs) == {"молоко": 2}
    assert parse_sku_spec("2", needs) == {"молоко": 2}


def test_parse_sku_rejects_garbage():
    with pytest.raises(PickError):
        parse_sku_spec("молоко=2, 1", ["молоко", "хлеб"])
    with pytest.raises(PickError):
        parse_sku_spec("9, 1, 1, 1", ["молоко"])
    with pytest.raises(PickError):
        parse_sku_spec("кола=1", ["молоко"])


def test_pick_changes_cart_unit_price_order():
    offers = [
        Offer("magnit", "молоко", "pack", "1.2 л", 99, None, "мл", 1200),
        Offer("magnit", "молоко", "liter", "1 л", 89, 110, "мл", 1000),
    ]
    ranked = ranked_choices(offers, ["молоко"], "magnit")
    assert ranked["молоко"][0][0].external_id == "pack"
    picked = pick_offers(ranked, {"молоко": 2})
    result = optimize_cart(["молоко"], offers, [], delivery_cost=0, selected=picked)
    assert result.best is not None
    assert result.best.lines[0].offer.external_id == "liter"
    with pytest.raises(PickError):
        pick_offers(ranked, {"молоко": 3})


def test_overlay_preferred_ignores_missing_and_out_of_stock():
    fresh = Offer("magnit", "молоко", "best", "1.2 л", 99, None, "мл", 1200)
    mine = Offer("magnit", "молоко", "mine", "Привычное", 89, 110, "мл", 1000)
    gone = Offer("magnit", "молоко", "old", "Старое", 70, None, "мл", 1000, in_stock=False)
    selected = overlay_preferred(
        [fresh, mine, gone],
        {"молоко": fresh},
        {("молоко", "magnit"): "mine", ("хлеб", "magnit"): "nope"},
    )
    assert selected["молоко"].external_id == "mine"
    kept = overlay_preferred([fresh, gone], {"молоко": fresh}, {("молоко", "magnit"): "old"})
    assert kept["молоко"].external_id == "best"


def test_purchase_roundtrip_and_alias(tmp_path):
    db = init_db(tmp_path / "app.db")
    offer = Offer("magnit", "молоко", "mine", "Привычное 1 л", 89, 110, "мл", 1000)
    result = optimize_cart(["молоко"], [offer], [], delivery_cost=500, selected={"молоко": offer})
    assert result.best is not None
    entry = record_purchase(
        baseline_total=result.baseline_total,
        calculated_total=result.best.total,
        paid_total=500,
        store=result.best.store,
        bought_at=datetime.now() - timedelta(days=1),
    )
    with sqlite3.connect(db) as conn:
        save_purchase(conn, entry, plan_breakdown(result.best))
        save_preferred(conn, [CartLine("молоко", offer)])
        loaded = load_entries(conn)
        preferred = load_preferred(conn, "magnit")
    assert loaded[0].saved == entry.saved
    assert loaded[0].paid_total == 500
    assert preferred[("молоко", "magnit")] == "mine"
    assert saved_since_midnight(loaded, now=datetime.now()) == 0
    assert summarize(loaded).month == entry.saved


def test_cli_sku_bought_records_second_variant(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr("cli.DB_PATH", tmp_path / "app.db")
    offers = [
        Offer("magnit", "молоко", "pack", "1.2 л", 99, 120, "мл", 1200),
        Offer("magnit", "молоко", "liter", "1 л", 89, 110, "мл", 1000),
    ]
    monkeypatch.setattr("cli._load_magnit", lambda needs, shelf=False: (offers, [], "тест"))
    monkeypatch.setattr("cli._collect_promos", lambda first_order: ([], []))
    monkeypatch.setattr("cli._magnit_preferred", lambda: {})
    code = main(["--sku", "2", "--paid", "500", "молоко"])
    assert code == 0
    out = capsys.readouterr().out
    assert "К оплате: 589 ₽" in out
    assert "Экономия сегодня: 110 ₽" in out
    with sqlite3.connect(tmp_path / "app.db") as conn:
        row = conn.execute("SELECT external_sku FROM aliases").fetchone()
        counted = load_entries(conn)
    assert row[0] == "liter"
    assert counted[0].saved == 110


def test_fake_bought_stays_out_of_savings(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr("cli.DB_PATH", tmp_path / "app.db")
    assert main(["--fake", "--sku", "2", "--bought", "молоко"]) == 0
    out = capsys.readouterr().out
    assert "в общий счёт" in out
    assert "Записал" not in out
    with sqlite3.connect(tmp_path / "app.db") as conn:
        assert load_entries(conn) == []
        assert conn.execute("SELECT COUNT(*) FROM aliases").fetchone()[0] == 0
        assert load_entries(conn, include_fake=True)


def test_cli_choose_can_decline(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr("cli.DB_PATH", tmp_path / "app.db")
    answers = iter(["2", "", "н"])

    def fake_input(prompt: str) -> str:
        return next(answers)

    code = main(["--fake", "--choose", "молоко"], input_fn=fake_input)
    assert code == 0
    out = capsys.readouterr().out
    assert "К ОПЛАТЕ: 592 ₽" in out
    assert "Записал" not in out
    assert not (tmp_path / "app.db").exists()


def test_cli_uses_remembered_magnit_sku(monkeypatch, capsys):
    offers = [
        Offer("magnit", "молоко", "best", "1.2 л", 99, None, "мл", 1200),
        Offer("magnit", "молоко", "mine", "Привычное", 89, 110, "мл", 1000),
    ]
    monkeypatch.setattr("cli._load_magnit", lambda needs, shelf=False: (offers, [], "тест"))
    monkeypatch.setattr("cli._collect_promos", lambda first_order: ([], []))
    monkeypatch.setattr("cli._magnit_preferred", lambda: {("молоко", "magnit"): "mine"})
    code = main(["молоко"])
    assert code == 0
    assert "✅ 2. Привычное" in capsys.readouterr().out


def test_cli_stats_and_conflicting_flags(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr("cli.DB_PATH", tmp_path / "app.db")
    assert main(["--stats"]) == 0
    assert "пока пусто" in capsys.readouterr().out
    assert main(["--sku", "1", "--choose", "--fake", "молоко"]) == 1
