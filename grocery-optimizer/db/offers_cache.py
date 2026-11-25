"""Кэш офферов Магнита в SQLite. Пустой ответ не кэшируется."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from config import OFFER_CACHE_HOURS
from domain.models import Offer


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _parse_ts(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def ensure_magnit_store(conn: sqlite3.Connection, store_code: str) -> int:
    row = conn.execute(
        "SELECT id, external_store_id FROM stores WHERE name = ?",
        ("magnit",),
    ).fetchone()
    if row:
        if row[1] != store_code:
            conn.execute(
                "UPDATE stores SET external_store_id = ? WHERE id = ?",
                (store_code, row[0]),
            )
        return int(row[0])
    cur = conn.execute(
        """
        INSERT INTO stores (name, title, city, external_store_id, delivery_cost_default, notes)
        VALUES ('magnit', 'Магнит', 'Барнаул', ?, 500, '')
        """,
        (store_code,),
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


def ensure_catalog_column(conn: sqlite3.Connection) -> None:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(offers)")}
    if "catalog_mode" not in cols:
        conn.execute(
            "ALTER TABLE offers ADD COLUMN catalog_mode TEXT NOT NULL DEFAULT ''"
        )


def load_offers(
    conn: sqlite3.Connection,
    *,
    need: str,
    store_code: str,
    catalog_mode: str = "",
    max_age_hours: float = OFFER_CACHE_HOURS,
    now: datetime | None = None,
) -> list[Offer] | None:
    """Свежий снимок или None, если кэша нет / он протух."""
    ensure_catalog_column(conn)
    store_id = ensure_magnit_store(conn, store_code)
    product = conn.execute(
        "SELECT id FROM products WHERE name_user = ?",
        (need,),
    ).fetchone()
    if product is None:
        return None

    rows = conn.execute(
        """
        SELECT external_sku, title, price, old_price, unit, qty, url, in_stock, scraped_at
        FROM offers
        WHERE product_id = ? AND store_id = ? AND catalog_mode = ?
        ORDER BY id
        """,
        (product[0], store_id, catalog_mode),
    ).fetchall()
    if not rows:
        return None

    moment = now or _utcnow()
    cutoff = moment - timedelta(hours=max_age_hours)
    offers: list[Offer] = []
    for sku, title, price, old_price, unit, qty, url, in_stock, scraped_at in rows:
        ts = _parse_ts(scraped_at or "")
        if ts is None or ts < cutoff:
            return None
        offers.append(
            Offer(
                store="magnit",
                need=need,
                external_id=str(sku or ""),
                title=str(title or ""),
                price=float(price),
                old_price=float(old_price) if old_price is not None else None,
                unit=str(unit or "шт"),
                qty=float(qty or 1),
                url=str(url or ""),
                in_stock=bool(in_stock),
            )
        )
    return offers


def save_offers(
    conn: sqlite3.Connection,
    offers: list[Offer],
    *,
    need: str,
    store_code: str,
    catalog_mode: str = "",
    scraped_at: datetime | None = None,
) -> None:
    if not offers:
        return
    ensure_catalog_column(conn)
    store_id = ensure_magnit_store(conn, store_code)
    product_id = _product_id(conn, need)
    conn.execute(
        "DELETE FROM offers WHERE product_id = ? AND store_id = ? AND catalog_mode = ?",
        (product_id, store_id, catalog_mode),
    )
    stamp = (scraped_at or _utcnow()).replace(microsecond=0).isoformat()
    conn.executemany(
        """
        INSERT INTO offers (
            product_id, store_id, external_sku, title, price, old_price,
            unit, qty, price_per_base, url, in_stock, catalog_mode, scraped_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                product_id,
                store_id,
                offer.external_id,
                offer.title,
                offer.price,
                offer.old_price,
                offer.unit,
                offer.qty,
                offer.price_per_base,
                offer.url,
                1 if offer.in_stock else 0,
                catalog_mode,
                stamp,
            )
            for offer in offers
        ],
    )
    conn.commit()
