"""Поиск товаров Магнита через тот же JSON, что дергает magnit.ru.

POST /webgate/v2/goods/search
Цены в ответе — копейки. shopCode: python -m tools.find_stores
Пятёрочка и Самокат сюда не входят.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

import httpx

import sqlite3

from db.offers_cache import load_offers, save_offers
from domain.matching import normalize_need
from domain.models import Offer
from parsers.base import BaseParser

SEARCH_PATH = "/webgate/v2/goods/search"
SEARCH_HOSTS = (
    "https://magnit.ru",
    "https://middle-api.magnit.ru",
)

VPN_HINT = (
    "Не удалось достучаться до каталога Магнита (DNS/SSL/сеть).\n"
    "Выключи VPN и повтори."
)

_MULTI = re.compile(
    r"(\d+)\s*[xх×*]\s*(\d+(?:[.,]\d+)?)\s*(мл|л|кг|г|шт)\b",
    re.IGNORECASE,
)
_SINGLE = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(мл|л|кг|г|шт)\b",
    re.IGNORECASE,
)


class MagnitNetworkError(RuntimeError):
    """DNS / SSL / connect — типично при VPN."""


class MagnitApiError(RuntimeError):
    """Каталог ответил ошибкой или непонятным JSON."""


def _to_base(value: float, unit: str) -> tuple[str, float]:
    unit = unit.lower()
    if unit == "л":
        return "мл", value * 1000
    if unit == "кг":
        return "г", value * 1000
    if unit == "мл":
        return "мл", value
    if unit == "г":
        return "г", value
    return "шт", value


def parse_pack(
    name: str,
    *,
    grammar: float | None = None,
    shelf_weight: float | None = None,
    is_weighted: bool = False,
) -> tuple[str, float]:
    """Фасовка в базовых единицах: мл, г или шт.

    Все жидкости сводятся к мл, весь вес — к г, чтобы цена за единицу
    сравнивалась между пачками одного запроса.
    """
    if is_weighted and shelf_weight and shelf_weight > 0:
        return "г", float(shelf_weight)

    text = name.replace("\xa0", " ")
    multi = _MULTI.search(text)
    if multi:
        count = float(multi.group(1))
        size = float(multi.group(2).replace(",", "."))
        unit, qty = _to_base(size, multi.group(3))
        return unit, count * qty

    singles = list(_SINGLE.finditer(text))
    if singles:
        last = singles[-1]
        size = float(last.group(1).replace(",", "."))
        return _to_base(size, last.group(2))

    if grammar and grammar > 0:
        return "г", float(grammar)
    return "шт", 1.0


def kopecks_to_rub(value: Any) -> float | None:
    """Целое число в ответе Магнита — копейки. Дробное уже в рублях."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return round(value / 100, 2)
    if isinstance(value, float):
        if value.is_integer():
            return round(value / 100, 2)
        return round(value, 2)
    try:
        number = float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None
    if number.is_integer():
        return round(number / 100, 2)
    return round(number, 2)


def goods_to_offer(item: dict, need: str, store_code: str) -> Offer | None:
    """Один товар из goods/search → Offer. None, если нет названия или цены."""
    title = str(item.get("name") or "").strip()
    price = kopecks_to_rub(item.get("price"))
    if not title or price is None or price <= 0:
        return None

    promo = item.get("promotion") or {}
    old_price = kopecks_to_rub(promo.get("oldPrice"))
    if old_price is not None and old_price <= price:
        old_price = None

    weighted = item.get("weighted") or {}
    is_weighted = bool(weighted.get("isWeighted"))
    shelf = weighted.get("shelfWeight")
    grammar = item.get("grammar")
    try:
        shelf_f = float(shelf) if shelf else None
    except (TypeError, ValueError):
        shelf_f = None
    try:
        grammar_f = float(grammar) if grammar else None
    except (TypeError, ValueError):
        grammar_f = None

    unit, qty = parse_pack(
        title,
        grammar=grammar_f,
        shelf_weight=shelf_f,
        is_weighted=is_weighted,
    )
    if qty <= 0:
        unit, qty = "шт", 1.0

    product_id = str(item.get("productId") or item.get("id") or "")
    if not product_id:
        return None
    seo = item.get("seoCode")
    if seo:
        url = f"https://magnit.ru/product/{product_id}-{seo}?shopCode={store_code}"
    else:
        url = f"https://magnit.ru/product/{product_id}?shopCode={store_code}"

    quantity = item.get("quantity")
    in_stock = True
    if isinstance(quantity, (int, float)) and quantity <= 0:
        in_stock = False

    return Offer(
        store="magnit",
        need=normalize_need(need),
        external_id=product_id,
        title=title,
        price=price,
        old_price=old_price,
        unit=unit,
        qty=qty,
        url=url,
        in_stock=in_stock,
    )


def _headers() -> dict[str, str]:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json",
        "Content-Type": "application/json",
        "x-device-id": str(uuid.uuid4()),
        "x-client-name": "magnit",
        "x-device-platform": "Web",
        "x-app-version": "8.45.0",
        "Origin": "https://magnit.ru",
        "Referer": "https://magnit.ru/",
    }


def _is_network_error(exc: BaseException) -> bool:
    if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout, httpx.TimeoutException)):
        return True
    msg = str(exc).lower()
    return any(
        x in msg
        for x in (
            "getaddrinfo",
            "name or service not known",
            "ssl",
            "unexpected_eof",
            "connection refused",
            "failed to resolve",
            "name resolution",
            "non-existent domain",
        )
    )


class MagnitParser(BaseParser):
    store = "magnit"

    def __init__(
        self,
        store_code: str = "",
        *,
        limit: int = 15,
        timeout: float = 30.0,
        catalog_type: str = "2",
        store_type: str = "dostavka",
        client: httpx.Client | None = None,
    ) -> None:
        self.store_code = store_code
        self.limit = limit
        self.timeout = timeout
        self.catalog_type = catalog_type
        self.store_type = store_type
        self._client = client
        self._owns_client = client is None
        self._base: str | None = None

    @property
    def catalog_mode(self) -> str:
        return f"{self.store_type}:{self.catalog_type}"

    def close(self) -> None:
        if self._owns_client and self._client is not None:
            self._client.close()
            self._client = None

    def __enter__(self) -> MagnitParser:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def _http(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=self.timeout)
        return self._client

    def _post_search(self, body: dict) -> dict:
        errors: list[str] = []
        hosts = [self._base] if self._base else list(SEARCH_HOSTS)
        last_status: int | None = None
        last_text = ""

        for host in hosts:
            if not host:
                continue
            url = f"{host}{SEARCH_PATH}"
            try:
                response = self._http().post(url, headers=_headers(), json=body)
            except Exception as exc:
                if _is_network_error(exc):
                    errors.append(f"{host}: {type(exc).__name__}")
                    continue
                raise
            if response.status_code >= 500 or response.status_code in (404, 403):
                last_status = response.status_code
                last_text = response.text[:300]
                continue
            if response.status_code >= 400:
                raise MagnitApiError(
                    f"Магнит {response.status_code} на {url}: {response.text[:400]}"
                )
            self._base = host
            try:
                data = response.json()
            except ValueError as exc:
                raise MagnitApiError(f"Магнит вернул не JSON: {exc}") from exc
            if not isinstance(data, dict):
                raise MagnitApiError("Магнит вернул не объект JSON")
            return data

        if errors and last_status is None:
            raise MagnitNetworkError(f"{VPN_HINT}\n({'; '.join(errors)})")
        raise MagnitApiError(
            f"Каталог Магнита недоступен (HTTP {last_status}). {last_text}"
        )

    def search(self, query: str) -> list[Offer]:
        if not self.store_code:
            raise RuntimeError(
                "Нет magnit storeCode. Запусти: python -m tools.find_stores"
            )
        body = {
            "term": query,
            "pagination": {"limit": self.limit, "offset": 0},
            "sort": {"order": "desc", "type": "popularity"},
            "includeAdultGoods": True,
            "storeCode": self.store_code,
            "storeType": self.store_type,
            "catalogType": self.catalog_type,
        }
        data = self._post_search(body)
        raw_items = data.get("items")
        if raw_items is None:
            raw_items = data.get("goods") or []
        offers: list[Offer] = []
        seen: set[str] = set()
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            offer = goods_to_offer(item, query, self.store_code)
            if offer is None or offer.external_id in seen:
                continue
            seen.add(offer.external_id)
            offers.append(offer)
        return offers

    def search_cached(self, conn: sqlite3.Connection, query: str) -> tuple[list[Offer], bool]:
        """Вернуть (офферы, из_кэша). Пустой ответ сети не записывается."""
        need = normalize_need(query)
        cached = load_offers(
            conn, need=need, store_code=self.store_code, catalog_mode=self.catalog_mode
        )
        if cached is not None:
            return cached, True
        offers = self.search(query)
        save_offers(
            conn,
            offers,
            need=need,
            store_code=self.store_code,
            catalog_mode=self.catalog_mode,
        )
        return offers, False
