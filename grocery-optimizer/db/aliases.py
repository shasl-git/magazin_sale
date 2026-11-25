"""Запомненный SKU: «это оно» для пары нужда + магазин."""

from __future__ import annotations

import sqlite3

from domain.models import CartLine


def load_preferred(conn: sqlite3.Connection, store: str) -> dict[tuple[str, str], str]:
    """(need, store) → external_sku последней подтверждённой покупки."""
    rows = conn.execute(
        """
        SELECT products.name_user, aliases.external_sku
        FROM aliases
        JOIN products ON products.id = aliases.product_id
        JOIN stores ON stores.id = aliases.store_id
        WHERE stores.name = ?
        ORDER BY aliases.id
        """,
        (store,),
    ).fetchall()
    return {(str(need), store): str(sku) for need, sku in rows}


def save_preferred(conn: sqlite3.Connection, lines: list[CartLine]) -> None:
    """Один предпочтительный SKU на нужду в магазине. Новая покупка заменяет прошлую."""
    for line in lines:
        store_id = _store_id(conn, line.offer.store)
        product_id = _product_id(conn, line.need)
        conn.execute(
            "DELETE FROM aliases WHERE product_id = ? AND store_id = ?",
            (product_id, store_id),
        )
        conn.execute(
            """
            INSERT INTO aliases (product_id, store_id, external_sku, title, unit, qty)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                product_id,
                store_id,
                line.offer.external_id,
                line.offer.title,
                line.offer.unit,
                line.offer.qty,
            ),
        )
    conn.commit()


def _store_id(conn: sqlite3.Connection, store: str) -> int:
    row = conn.execute(
        "SELECT id FROM stores WHERE name = ?",
        (store,),
    ).fetchone()
    if row:
        return int(row[0])
    cur = conn.execute(
        """
        INSERT INTO stores (name, title, city, external_store_id, delivery_cost_default, notes)
        VALUES (?, ?, 'Барнаул', '', 500, '')
        """,
        (store, store),
    )
    return int(cur.lastrowid)


def _product_id(conn: sqlite3.Connection, need: str) -> int:
    row = conn.execute(
        "SELECT id FROM products WHERE name_user = ?",
        (need,),
    ).fetchone()
    if row:
        return int(row[0])
    cur = conn.execute(
        "INSERT INTO products (name_user) VALUES (?)",
        (need,),
    )
    return int(cur.lastrowid)
