"""Ручные корзинные акции Магнита. Источник — то, что видно в приложении."""

from __future__ import annotations

import json
import sqlite3

from db.offers_cache import ensure_magnit_store
from domain.models import Promo

MANUAL = "manual"


def _rules(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def load_manual_promos(conn: sqlite3.Connection, store_code: str) -> list[Promo]:
    store_id = ensure_magnit_store(conn, store_code)
    rows = conn.execute(
        """
        SELECT type, title, threshold, discount_value, discount_kind, rules_json
        FROM promos
        WHERE store_id = ?
        ORDER BY id
        """,
        (store_id,),
    ).fetchall()
    promos: list[Promo] = []
    for promo_type, title, threshold, value, kind, rules_json in rows:
        if _rules(rules_json).get("source") != MANUAL:
            continue
        promos.append(
            Promo(
                store="magnit",
                type=promo_type,
                title=str(title or promo_type),
                threshold=float(threshold) if threshold is not None else None,
                discount_value=float(value) if value is not None else None,
                discount_kind=kind,
            )
        )
    return promos


def replace_manual_promo(conn: sqlite3.Connection, store_code: str, promo: Promo) -> None:
    """Одна ручная акция данного type: новая запись заменяет предыдущую того же type."""
    store_id = ensure_magnit_store(conn, store_code)
    rows = conn.execute(
        "SELECT id, rules_json FROM promos WHERE store_id = ? AND type = ?",
        (store_id, promo.type),
    ).fetchall()
    for row_id, rules_json in rows:
        if _rules(rules_json).get("source") == MANUAL:
            conn.execute("DELETE FROM promos WHERE id = ?", (row_id,))
    conn.execute(
        """
        INSERT INTO promos (store_id, type, title, threshold, discount_value, discount_kind, rules_json)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            store_id,
            promo.type,
            promo.title,
            promo.threshold,
            promo.discount_value,
            promo.discount_kind,
            json.dumps({"source": MANUAL}, ensure_ascii=False),
        ),
    )
    conn.commit()


def clear_manual_promos(conn: sqlite3.Connection, store_code: str) -> int:
    store_id = ensure_magnit_store(conn, store_code)
    rows = conn.execute(
        "SELECT id, rules_json FROM promos WHERE store_id = ?",
        (store_id,),
    ).fetchall()
    removed = 0
    for row_id, rules_json in rows:
        if _rules(rules_json).get("source") == MANUAL:
            conn.execute("DELETE FROM promos WHERE id = ?", (row_id,))
            removed += 1
    conn.commit()
    return removed
