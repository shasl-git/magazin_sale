"""Количество в списке и полный проход в терминале."""

from __future__ import annotations

import sqlite3
from datetime import datetime

from db import init_db
from db.purchases import last_live_items, plan_breakdown, save_purchase
from domain.matching import parse_items, parse_list
from domain.models import Offer
from domain.optimizer import optimize_cart
from domain.savings import record_purchase

from cli import main


def test_parse_items_keeps_pack_size_and_explicit_count():
    assert parse_items("молоко x2, хлеб, 3 x яйца, сахар 2 шт") == [
        ("молоко", 2),
        ("хлеб", 1),
        ("яйца", 3),
        ("сахар", 2),
    ]
    assert parse_items("сок 6х200 мл") == [("сок 6х200 мл", 1)]
    assert parse_items("молоко, молоко") == [("молоко", 1)]
    assert parse_items("молоко x2, молоко x1") == [("молоко", 3)]
    assert parse_list("2 шт кола") == ["кола"]


def test_cli_plan_multiplies_quantity(capsys):
    assert main(["--fake", "--plan", "молоко x2"]) == 0
    out = capsys.readouterr().out
    assert "молоко ×2" in out
    assert "×2 = 170 ₽" in out
    assert "К оплате: 670 ₽" in out


def test_tty_session_can_set_delivery_and_stop(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr("cli.DB_PATH", tmp_path / "app.db")
    answers = iter(["", "0", "н"])

    def fake_input(_prompt: str) -> str:
        return next(answers)

    code = main(["--fake", "молоко"], input_fn=fake_input, assume_tty=True)
    assert code == 0
    out = capsys.readouterr().out
    assert "К ОПЛАТЕ: 85 ₽" in out
    assert "Записал" not in out
    assert not (tmp_path / "app.db").exists()


def test_saved_count_comes_back_on_again(monkeypatch, tmp_path, capsys):
    db = tmp_path / "app.db"
    monkeypatch.setattr("cli.DB_PATH", db)
    init_db(db)
    offer = Offer("magnit", "молоко", "1", "Молоко", 100, 120, "мл", 1000)
    result = optimize_cart(
        ["молоко"],
        [offer],
        [],
        delivery_cost=0,
        counts={"молоко": 2},
    )
    assert result.best is not None
    entry = record_purchase(
        baseline_total=result.baseline_total,
        calculated_total=result.best.total,
        paid_total=result.best.total,
        store="magnit",
        bought_at=datetime(2026, 11, 21, 10, 0, 0),
    )
    with sqlite3.connect(db) as conn:
        save_purchase(conn, entry, plan_breakdown(result.best))
        _bought_at, items = last_live_items(conn)
    assert items == [("молоко", 2)]
    assert main(["--fake", "--plan", "--again"]) == 0
    out = capsys.readouterr().out
    assert "молоко ×2" in out
    assert "Повтор закупки от 21.11.2026" in out
