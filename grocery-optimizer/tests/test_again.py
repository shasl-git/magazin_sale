"""Повтор прошлой закупки и доставка на один запуск."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta

from db import init_db
from db.purchases import last_live_needs, plan_breakdown, save_purchase
from domain.models import Offer
from domain.optimizer import optimize_cart
from domain.savings import record_purchase

from cli import main


def _save(db, needs: list[str], *, source: str, bought_at: datetime) -> None:
    offers = [
        Offer("magnit", need, f"sku-{need}", need, 100, 120, "шт", 1) for need in needs
    ]
    result = optimize_cart(
        needs,
        offers,
        [],
        delivery_cost=500,
        selected={need: offer for need, offer in zip(needs, offers)},
    )
    assert result.best is not None
    entry = record_purchase(
        baseline_total=result.baseline_total,
        calculated_total=result.best.total,
        paid_total=result.best.total,
        store="magnit",
        bought_at=bought_at,
    )
    with sqlite3.connect(db) as conn:
        save_purchase(conn, entry, plan_breakdown(result.best, source=source))


def test_last_live_needs_skips_newer_fake(tmp_path):
    db = init_db(tmp_path / "app.db")
    now = datetime.now()
    _save(db, ["молоко", "хлеб"], source="live", bought_at=now - timedelta(days=3))
    _save(db, ["кола"], source="fake", bought_at=now)
    with sqlite3.connect(db) as conn:
        bought_at, needs = last_live_needs(conn)
    assert needs == ["молоко", "хлеб"]
    assert bought_at.date() == (now - timedelta(days=3)).date()


def test_cli_again_repeats_and_appends(monkeypatch, tmp_path, capsys):
    db = tmp_path / "app.db"
    monkeypatch.setattr("cli.DB_PATH", db)
    init_db(db)
    _save(db, ["молоко", "хлеб"], source="live", bought_at=datetime(2026, 11, 20, 12, 0, 0))
    assert main(["--fake", "--again"]) == 0
    first = capsys.readouterr().out
    assert "Повтор закупки от 20.11.2026: молоко, хлеб" in first
    assert "Список: молоко, хлеб" in first

    assert main(["--fake", "--again", "сахар"]) == 0
    second = capsys.readouterr().out
    assert "молоко, хлеб + сахар" in second
    assert "Список: молоко, хлеб, сахар" in second


def test_cli_again_without_history(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr("cli.DB_PATH", tmp_path / "app.db")
    assert main(["--again"]) == 1
    assert "Живых покупок ещё нет" in capsys.readouterr().out


def test_cli_delivery_overrides_default(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr("cli.DB_PATH", tmp_path / "app.db")
    assert main(["--fake", "--delivery", "0", "молоко"]) == 0
    out = capsys.readouterr().out
    assert "если порог не взят: 0 ₽" in out
    assert "К оплате: 85 ₽" in out
    assert main(["--fake", "--delivery", "-1", "молоко"]) == 1
