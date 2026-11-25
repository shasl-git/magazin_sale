"""Выбор магазина Магнита: список → номер → запись shopCode.

Примеры:
  python -m tools.find_stores
  python -m tools.find_stores --query "Барнаул Павловский"
  python -m tools.find_stores --list-only
  python -m tools.find_stores --pick 1
  python -m tools.find_stores --address-contains Шумакова

Пятёрочка (sapCode) — отдельным шагом позже; этот инструмент только Магнит.
"""

from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import DB_PATH, STORES, USER  # noqa: E402
from db import init_db  # noqa: E402
from parsers.magnit_stores import (  # noqa: E402
    INDUSTRIAL_LAT,
    INDUSTRIAL_LON,
    MagnitNetworkError,
    MagnitStore,
    VPN_HINT,
    find_stores,
)


def _patch_config(store_code: str) -> None:
    path = ROOT / "config.py"
    text = path.read_text(encoding="utf-8")
    new, n = re.subn(
        r'(magnit_store_code:\s*str\s*=\s*)"[^"]*"',
        rf'\1"{store_code}"',
        text,
        count=1,
    )
    if n == 0:
        raise RuntimeError("Не нашёл magnit_store_code в config.py")
    path.write_text(new, encoding="utf-8")
    STORES.magnit_store_code = store_code


def _save_db(store: MagnitStore) -> None:
    init_db()
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT id FROM stores WHERE name = ?", ("magnit",)
        ).fetchone()
        title = f"{store.type_label} · {store.address}"
        notes = f"{USER.district}; lat={store.lat}, lon={store.lon}"
        if row:
            conn.execute(
                """
                UPDATE stores
                SET title = ?, external_store_id = ?, notes = ?,
                    delivery_cost_default = ?, city = ?
                WHERE id = ?
                """,
                (
                    title,
                    store.store_code,
                    notes,
                    USER.delivery_cost_default,
                    USER.city,
                    row[0],
                ),
            )
        else:
            conn.execute(
                """
                INSERT INTO stores
                  (name, title, city, external_store_id, delivery_cost_default, notes)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    "magnit",
                    title,
                    USER.city,
                    store.store_code,
                    USER.delivery_cost_default,
                    notes,
                ),
            )
        conn.commit()


def _print_list(stores: list[MagnitStore]) -> None:
    if not stores:
        print("Ничего не найдено. Попробуй --query с улицей или --address-contains.")
        return
    print(f"\nМагниты рядом с {USER.district} ({USER.city}):\n")
    for i, s in enumerate(stores, 1):
        km = s.distance_km(INDUSTRIAL_LAT, INDUSTRIAL_LON)
        print(f"  {i:2}. [{s.store_code}] {s.type_label} · {s.address}  (~{km:.1f} км)")
    print()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Выбрать магазин Магнита и сохранить shopCode"
    )
    parser.add_argument(
        "--query",
        default=USER.city,
        help='Строка поиска (по умолчанию город → точки вокруг Индустриального)',
    )
    parser.add_argument("--limit", type=int, default=15, help="Сколько точек показать")
    parser.add_argument(
        "--pick",
        "--select",
        type=int,
        default=None,
        dest="pick",
        help="Номер из списка без интерактива (1-based)",
    )
    parser.add_argument(
        "--list-only",
        action="store_true",
        help="Только показать список, не сохранять",
    )
    parser.add_argument(
        "--address-contains",
        default=None,
        help='Фильтр по подстроке адреса, напр. "Павловский" или "Шумакова"',
    )
    args = parser.parse_args(argv)

    print(f"Ищу Магниты около {USER.district}: query={args.query!r} …")
    try:
        stores = find_stores(
            args.query,
            limit=args.limit,
            address_contains=args.address_contains,
        )
    except MagnitNetworkError as e:
        print(str(e))
        return 2
    except Exception as e:
        if any(x in str(e).lower() for x in ("ssl", "getaddrinfo", "connect", "resolve")):
            print(VPN_HINT)
            print(f"Детали: {e}")
            return 2
        print(f"Ошибка API Магнита: {e}")
        print(VPN_HINT)
        return 1

    _print_list(stores)
    if not stores or args.list_only:
        return 0 if stores else 1

    if args.pick is not None:
        idx = args.pick
    else:
        raw = input(f"Выбери номер 1–{len(stores)} (Enter = 1): ").strip()
        idx = int(raw) if raw else 1

    if idx < 1 or idx > len(stores):
        print("Неверный номер.")
        return 1

    chosen = stores[idx - 1]
    _patch_config(chosen.store_code)
    _save_db(chosen)
    print(f"Сохранено: shopCode={chosen.store_code}")
    print(f"  {chosen.type_label} · {chosen.address}")
    print("  → config.py (STORES.magnit_store_code) и db/app.db")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
