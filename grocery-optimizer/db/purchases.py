"""История покупок в savings_log."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from domain.models import CartPlan
from domain.savings import SavingsEntry


def save_purchase(
    conn: sqlite3.Connection,
    entry: SavingsEntry,
    breakdown: dict,
) -> int:
    cur = conn.execute(
        """
        INSERT INTO savings_log (
            bought_at, store_ids, baseline_total, calculated_total,
            paid_total, saved, breakdown_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            entry.bought_at.isoformat(timespec="seconds"),
            json.dumps([entry.store], ensure_ascii=False),
            entry.baseline_total,
            entry.calculated_total,
            entry.paid_total,
            entry.saved,
            json.dumps(breakdown, ensure_ascii=False),
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


def load_entries(conn: sqlite3.Connection, *, include_fake: bool = False) -> list[SavingsEntry]:
    rows = conn.execute(
        """
        SELECT bought_at, store_ids, baseline_total, calculated_total, paid_total, saved, breakdown_json
        FROM savings_log
        ORDER BY bought_at
        """
    ).fetchall()
    entries: list[SavingsEntry] = []
    for bought_at, store_ids, baseline, calculated, paid, saved, breakdown_json in rows:
        if not include_fake and _source(breakdown_json) == "fake":
            continue
        entries.append(
            SavingsEntry(
                bought_at=datetime.fromisoformat(bought_at),
                store=_store_name(store_ids),
                baseline_total=float(baseline),
                calculated_total=float(calculated),
                paid_total=float(paid if paid is not None else calculated),
                saved=float(saved),
            )
        )
    return entries


def last_live_items(conn: sqlite3.Connection) -> tuple[datetime, list[tuple[str, int]]] | None:
    """Последняя живая покупка: дата и позиции с количеством."""
    rows = conn.execute(
        """
        SELECT bought_at, breakdown_json
        FROM savings_log
        ORDER BY bought_at DESC, id DESC
        """
    ).fetchall()
    for bought_at, raw in rows:
        if _source(raw) == "fake":
            continue
        items = _items_from_breakdown(raw)
        if items:
            return datetime.fromisoformat(bought_at), items
    return None


def last_live_needs(conn: sqlite3.Connection) -> tuple[datetime, list[str]] | None:
    """Последняя живая покупка: дата и список нужд в том же порядке."""
    found = last_live_items(conn)
    if found is None:
        return None
    bought_at, items = found
    return bought_at, [name for name, _count in items]


def plan_breakdown(plan: CartPlan, *, source: str = "live") -> dict:
    return {
        "source": source,
        "store": plan.store,
        "lines": [
            {
                "need": line.need,
                "external_id": line.offer.external_id,
                "title": line.offer.title,
                "price": line.offer.price,
                "old_price": line.offer.old_price,
                "count": line.count,
            }
            for line in plan.lines
        ],
        "subtotal": plan.subtotal,
        "discount": plan.discount,
        "delivery": plan.delivery,
        "total": plan.total,
        "applied_promos": list(plan.applied_promos),
    }


def _items_from_breakdown(raw: str | None) -> list[tuple[str, int]]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    lines = data.get("lines") if isinstance(data, dict) else None
    if not isinstance(lines, list):
        return []
    items: list[tuple[str, int]] = []
    seen: set[str] = set()
    for line in lines:
        if not isinstance(line, dict):
            continue
        need = str(line.get("need") or "").strip()
        if not need or need in seen:
            continue
        seen.add(need)
        try:
            count = int(line.get("count") or 1)
        except (TypeError, ValueError):
            count = 1
        items.append((need, count if count >= 1 else 1))
    return items


def _source(raw: str | None) -> str:
    if not raw:
        return "live"
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return "live"
    if isinstance(data, dict):
        return str(data.get("source") or "live")
    return "live"


def _store_name(raw: str | None) -> str:
    if not raw:
        return ""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return raw
    if isinstance(data, list) and data:
        return str(data[0])
    return str(data)
