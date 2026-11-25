"""Инициализация SQLite из schema.sql."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from config import DB_PATH, ROOT, USER


SCHEMA_PATH = ROOT / "db" / "schema.sql"


def init_db(path: Path | None = None) -> Path:
    db_path = path or DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)
    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    with sqlite3.connect(db_path) as conn:
        conn.executescript(schema)
        _seed_stores(conn)
    return db_path


def _seed_stores(conn: sqlite3.Connection) -> None:
    row = conn.execute("SELECT COUNT(*) FROM stores").fetchone()
    if row and row[0] > 0:
        return
    # external_store_id пустой — заполним после ручного выбора точки
    conn.executemany(
        """
        INSERT INTO stores (name, title, city, external_store_id, delivery_cost_default, notes)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        [
            (
                "magnit",
                "Магнит (Индустриальный)",
                USER.city,
                "",
                USER.delivery_cost_default,
                USER.district,
            ),
            (
                "pyaterochka",
                "Пятёрочка (Индустриальный)",
                USER.city,
                "",
                USER.delivery_cost_default,
                USER.district,
            ),
            (
                "samokat",
                "Самокат (Индустриальный)",
                USER.city,
                "",
                USER.delivery_cost_default,
                "позже",
            ),
        ],
    )
    conn.commit()
