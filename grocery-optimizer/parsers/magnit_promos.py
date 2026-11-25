"""Корзинная акция с главной magnit.ru.

Сейчас сайт показывает скидку на первый заказ доставки (промокод на баннере).
Постоянный порог «на каждый заказ» и бесплатная доставка туда не входят —
их задают вручную: python -m tools.set_promo.
"""

from __future__ import annotations

import re

import httpx

from domain.models import Promo

_DISCOUNT = re.compile(r"Скидка\s+(\d+)\s*%\s+на первый заказ", re.IGNORECASE)
_THRESHOLD = re.compile(r"От\s+([\d\s\u00a0]+)\s*₽", re.IGNORECASE)
_CODE = re.compile(r"\b([A-ZА-ЯЁ]{2,10}\d{1,4})\b")


def parse_first_order_banner(html: str) -> Promo | None:
    """Разобрать баннер «скидка на первый заказ». None, если баннера нет."""
    text = re.sub(r"<[^>]+>", " ", html)
    text = text.replace("\xa0", " ").replace("&nbsp;", " ")
    text = re.sub(r"\s+", " ", text)
    discount = _DISCOUNT.search(text)
    if not discount:
        return None
    window = text[discount.start() : discount.start() + 500]
    threshold_match = _THRESHOLD.search(window)
    if not threshold_match:
        return None
    threshold = float(re.sub(r"\s+", "", threshold_match.group(1)))
    percent = int(discount.group(1))
    if percent <= 0 or percent >= 100 or threshold <= 0:
        return None
    code_match = _CODE.search(window)
    code = code_match.group(1) if code_match else ""
    title = f"−{percent}% от {threshold:.0f} ₽"
    if code:
        title += f", промокод {code}"
    title += " (первый заказ)"
    return Promo(
        store="magnit",
        type="cart_threshold",
        title=title,
        threshold=threshold,
        discount_value=percent / 100,
        discount_kind="percent",
    )


def fetch_first_order_promo(timeout: float = 20.0) -> Promo | None:
    """Один GET главной. Сеть или вёрстка могли сломаться — тогда None."""
    try:
        response = httpx.get(
            "https://magnit.ru/",
            headers={"User-Agent": "Mozilla/5.0", "Accept": "text/html"},
            timeout=timeout,
            follow_redirects=True,
        )
        response.raise_for_status()
    except (httpx.HTTPError, OSError):
        return None
    return parse_first_order_banner(response.text)
