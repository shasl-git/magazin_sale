"""Поиск точек Магнита и получение shopCode без DevTools.

Рабочий host: https://middle-api.magnit.ru
  GET  /shops/v1/shop_by_point?x={lat}&y={lon}  → shops[].xml_id (= shopCode)
  POST /v1/stores-facade/search  body {"filters":{"query":"Барнаул"}}
  POST /v1/stores-facade/store   body {"externalId":{"owner":"OWNER_MAGNIT","storeCode":"..."}}

web-gateway.middle-api.magnit.ru часто NXDOMAIN / не резолвится.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass

import httpx

API_HOSTS = (
    "https://middle-api.magnit.ru",
    "https://web-gateway.middle-api.magnit.ru",
)

VPN_HINT = (
    "Не удалось достучаться до API Магнита (DNS/SSL/сеть).\n"
    "Выключи VPN (или Safe DNS) и запусти снова:\n"
    "  python -m tools.find_stores"
)

TYPE_LABEL = {
    "STORE_TYPE_MM": "Магнит",
    "STORE_TYPE_GM": "Гипер",
    "STORE_TYPE_DG": "Семейный",
    "STORE_TYPE_MA": "Магнит",
    "STORE_TYPE_ME": "Экстра",
    "STORE_TYPE_MC": "Косметик",
    # числовые типы из shop_by_point
    "1": "Магнит",
    "2": "Гипер",
    "3": "Косметик / другое",
}

# Центр Индустриального района Барнаула (примерно)
INDUSTRIAL_LAT = 53.347
INDUSTRIAL_LON = 83.670


class MagnitNetworkError(RuntimeError):
    """DNS / SSL / connect — типично при VPN / Safe DNS."""


@dataclass(frozen=True)
class MagnitStore:
    store_code: str
    address: str
    store_type: str
    lat: float
    lon: float
    city_fias_id: str = ""
    is_active: bool = True

    @property
    def type_label(self) -> str:
        return TYPE_LABEL.get(self.store_type, self.store_type or "?")

    def distance_km(self, lat: float, lon: float) -> float:
        r = 6371.0
        p1, p2 = math.radians(lat), math.radians(self.lat)
        dphi = math.radians(self.lat - lat)
        dlmb = math.radians(self.lon - lon)
        a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
        return 2 * r * math.asin(math.sqrt(a))


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
        "Referer": "https://magnit.ru/shops",
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
            "nodename nor servname",
            "ssl",
            "unexpected_eof",
            "connection refused",
            "failed to resolve",
            "name resolution",
            "non-existent domain",
        )
    )


class MagnitApiClient:
    """Клиент с автовыбором рабочего host."""

    def __init__(self, timeout: float = 30.0) -> None:
        self.timeout = timeout
        self.base: str | None = None
        self._client = httpx.Client(timeout=timeout)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> MagnitApiClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def _request(self, method: str, path: str, *, json_body: dict | None = None, params: dict | None = None) -> httpx.Response:
        headers = _headers()
        errors: list[str] = []
        hosts = [self.base] if self.base else list(API_HOSTS)

        for host in hosts:
            if not host:
                continue
            url = f"{host}{path}"
            try:
                r = self._client.request(
                    method, url, headers=headers, json=json_body, params=params
                )
                self.base = host
                return r
            except Exception as e:
                if _is_network_error(e):
                    errors.append(f"{host}: {type(e).__name__}: {e}")
                    continue
                raise

        detail = "; ".join(errors) if errors else "нет ответа"
        raise MagnitNetworkError(f"{VPN_HINT}\n({detail})")

    def _post(self, path: str, body: dict) -> httpx.Response:
        return self._request("POST", path, json_body=body)

    def _get(self, path: str, params: dict) -> httpx.Response:
        return self._request("GET", path, params=params)

    def search(self, query: str) -> list[dict]:
        r = self._post("/v1/stores-facade/search", {"filters": {"query": query}})
        r.raise_for_status()
        items = (((r.json().get("items") or {}).get("items")) or [])
        return [i for i in items if isinstance(i, dict)]

    def shop_by_point(self, lat: float, lon: float) -> list[dict]:
        """Ближайшие точки. x=широта, y=долгота (как у сайта)."""
        r = self._get("/shops/v1/shop_by_point", {"x": lat, "y": lon})
        r.raise_for_status()
        shops = r.json().get("shops") or []
        return [s for s in shops if isinstance(s, dict)]

    def store_detail(self, store_code: str, owner: str = "OWNER_MAGNIT") -> MagnitStore | None:
        r = self._post(
            "/v1/stores-facade/store",
            {"externalId": {"owner": owner, "storeCode": store_code}},
        )
        if r.status_code != 200:
            return None
        data = r.json()
        coords = data.get("coordinates") or {}
        ext = data.get("externalId") or {}
        return MagnitStore(
            store_code=str(ext.get("storeCode") or store_code),
            address=str(data.get("address") or ""),
            store_type=str(data.get("storeType") or ""),
            lat=float(coords.get("latitude") or 0),
            lon=float(coords.get("longitude") or 0),
            city_fias_id=str(data.get("cityFiasId") or ""),
            is_active=bool(data.get("isActive", True)),
        )


def _is_grocery_summary(summary: dict) -> bool:
    st = summary.get("storeType") or ""
    if "PHARMACY" in st or "DISTR" in st:
        return False
    code = ((summary.get("externalId") or {}).get("storeCode")) or ""
    if not str(code).isdigit():
        return False
    if st == "STORE_TYPE_MC":
        return False
    return True


def _is_grocery_point(shop: dict) -> bool:
    """shop_by_point: store_type 3 часто косметик — отсекаем."""
    code = str(shop.get("xml_id") or "")
    if not code.isdigit():
        return False
    st = shop.get("store_type")
    if st in (3, "3"):
        return False
    return bool(shop.get("active", True))


def _grid_around(lat: float, lon: float, *, step: float = 0.015, rings: int = 2) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = [(lat, lon)]
    for r in range(1, rings + 1):
        for dlat in range(-r, r + 1):
            for dlon in range(-r, r + 1):
                if abs(dlat) != r and abs(dlon) != r:
                    continue
                points.append((lat + dlat * step, lon + dlon * step))
    return points


def find_stores_near(
    lat: float = INDUSTRIAL_LAT,
    lon: float = INDUSTRIAL_LON,
    *,
    limit: int = 20,
    address_contains: str | None = None,
    client: MagnitApiClient | None = None,
) -> list[MagnitStore]:
    """Сетка точек вокруг района → shop_by_point → детали адреса."""
    own = client or MagnitApiClient()
    close = client is None
    try:
        seen: dict[str, dict] = {}
        for plat, plon in _grid_around(lat, lon):
            for shop in own.shop_by_point(plat, plon):
                if not _is_grocery_point(shop):
                    continue
                code = str(shop["xml_id"])
                if code not in seen:
                    seen[code] = shop

        # сортируем сырые точки по расстоянию до центра района
        def _raw_dist(s: dict) -> float:
            c = s.get("coordinates") or {}
            try:
                return MagnitStore(
                    store_code="x",
                    address="",
                    store_type="",
                    lat=float(c.get("x") or 0),
                    lon=float(c.get("y") or 0),
                ).distance_km(lat, lon)
            except (TypeError, ValueError):
                return 1e9

        ordered = sorted(seen.values(), key=_raw_dist)
        results: list[MagnitStore] = []
        for shop in ordered:
            if len(results) >= limit:
                break
            code = str(shop["xml_id"])
            detail = own.store_detail(code)
            if detail is None:
                # fallback без facade detail
                c = shop.get("coordinates") or {}
                detail = MagnitStore(
                    store_code=code,
                    address=str(shop.get("formatted_address") or ""),
                    store_type=str(shop.get("store_type") or ""),
                    lat=float(c.get("x") or 0),
                    lon=float(c.get("y") or 0),
                    is_active=bool(shop.get("active", True)),
                )
            if not detail.address:
                continue
            if address_contains and address_contains.lower() not in detail.address.lower():
                continue
            if not detail.is_active:
                continue
            results.append(detail)

        results.sort(key=lambda st: st.distance_km(lat, lon))
        return results
    finally:
        if close:
            own.close()


def find_stores(
    query: str = "Барнаул",
    *,
    near_lat: float | None = INDUSTRIAL_LAT,
    near_lon: float | None = INDUSTRIAL_LON,
    limit: int = 20,
    address_contains: str | None = None,
    prefer_near: bool = True,
) -> list[MagnitStore]:
    """
    Найти продуктовые Магниты.

    По умолчанию: сетка вокруг Индустриального (shop_by_point).
    Если передан нестандартный query (не просто город) — stores-facade/search.
    """
    cityish = query.strip().lower() in {"", "барнаул", "barnaul"}
    if prefer_near and cityish and near_lat is not None and near_lon is not None:
        near = find_stores_near(
            near_lat,
            near_lon,
            limit=limit,
            address_contains=address_contains,
        )
        if near:
            return near

    with MagnitApiClient() as api:
        summaries = [s for s in api.search(query) if _is_grocery_summary(s)]

        if near_lat is not None and near_lon is not None:

            def _dist(s: dict) -> float:
                c = s.get("coordinates") or {}
                try:
                    return MagnitStore(
                        store_code="x",
                        address="",
                        store_type="",
                        lat=float(c.get("latitude") or 0),
                        lon=float(c.get("longitude") or 0),
                    ).distance_km(near_lat, near_lon)
                except (TypeError, ValueError):
                    return 1e9

            summaries.sort(key=_dist)

        results: list[MagnitStore] = []
        for s in summaries:
            if len(results) >= limit:
                break
            code = (s.get("externalId") or {}).get("storeCode")
            owner = (s.get("externalId") or {}).get("owner") or "OWNER_MAGNIT"
            if not code:
                continue
            detail = api.store_detail(str(code), owner=str(owner))
            if detail is None or not detail.address:
                continue
            if address_contains and address_contains.lower() not in detail.address.lower():
                continue
            if not detail.is_active:
                continue
            results.append(detail)

    if near_lat is not None and near_lon is not None:
        results.sort(key=lambda st: st.distance_km(near_lat, near_lon))
    return results
