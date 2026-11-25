"""Ручные акции Магнита, которые сайт не отдаёт без входа в корзину.

Примеры:
  python -m tools.set_promo --list
  python -m tools.set_promo --percent 1500 20
  python -m tools.set_promo --amount 800 300
  python -m tools.set_promo --free-delivery 1000
  python -m tools.set_promo --clear
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import DB_PATH, STORES  # noqa: E402
from db import init_db  # noqa: E402
from db.manual_promos import clear_manual_promos, load_manual_promos, replace_manual_promo  # noqa: E402
from domain.models import Promo  # noqa: E402


def _print(promos: list[Promo]) -> None:
    if not promos:
        print("Ручных акций Магнита нет.")
        print("Доставка в расчёте остаётся из config: 500 ₽, пока не задашь --free-delivery.")
        return
    print("Ручные акции Магнита:")
    for promo in promos:
        print(f"  • {promo.type}: {promo.title}")


def main(argv: list[str] | None = None) -> int:
    if not STORES.magnit_store_code:
        print("Нет shopCode. Сначала: python -m tools.find_stores")
        return 2
    parser = argparse.ArgumentParser(description="Записать корзинную акцию Магнита вручную")
    parser.add_argument("--list", action="store_true", help="Показать записанные акции")
    parser.add_argument(
        "--percent",
        nargs=2,
        type=float,
        metavar=("ПОРОГ", "ПРОЦЕНТ"),
        help="Скидка в процентах от суммы, например: --percent 1500 20",
    )
    parser.add_argument(
        "--amount",
        nargs=2,
        type=float,
        metavar=("ПОРОГ", "РУБЛИ"),
        help="Скидка суммой от порога, например: --amount 800 300",
    )
    parser.add_argument(
        "--free-delivery",
        type=float,
        metavar="ПОРОГ",
        help="Доставка 0 ₽ от этой суммы корзины",
    )
    parser.add_argument("--clear", action="store_true", help="Удалить ручные акции")
    args = parser.parse_args(argv)

    init_db()
    with sqlite3.connect(DB_PATH) as conn:
        if args.clear:
            removed = clear_manual_promos(conn, STORES.magnit_store_code)
            print(f"Удалено ручных акций: {removed}")
        if args.percent:
            threshold, percent = args.percent
            if percent <= 0 or percent >= 100 or threshold <= 0:
                print("Процент от 1 до 99, порог больше 0.")
                return 1
            replace_manual_promo(
                conn,
                STORES.magnit_store_code,
                Promo(
                    "magnit",
                    "cart_threshold",
                    f"−{percent:.0f}% от {threshold:.0f} ₽",
                    threshold=threshold,
                    discount_value=percent / 100,
                    discount_kind="percent",
                ),
            )
        if args.amount:
            threshold, amount = args.amount
            if amount <= 0 or threshold <= 0:
                print("Сумма и порог должны быть больше 0.")
                return 1
            replace_manual_promo(
                conn,
                STORES.magnit_store_code,
                Promo(
                    "magnit",
                    "cart_threshold",
                    f"−{amount:.0f} ₽ от {threshold:.0f} ₽",
                    threshold=threshold,
                    discount_value=amount,
                    discount_kind="amount",
                ),
            )
        if args.free_delivery is not None:
            if args.free_delivery <= 0:
                print("Порог доставки должен быть больше 0.")
                return 1
            replace_manual_promo(
                conn,
                STORES.magnit_store_code,
                Promo(
                    "magnit",
                    "free_delivery",
                    f"Доставка 0 ₽ от {args.free_delivery:.0f} ₽",
                    threshold=args.free_delivery,
                ),
            )
        _print(load_manual_promos(conn, STORES.magnit_store_code))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
