"""Локальный сайт: http://127.0.0.1:8787"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from web.service import (
    PlanError,
    list_shop_points,
    list_visible_promos,
    load_meta,
    load_stats,
    queue_plan,
    read_plan_job,
    recalculate,
    record_purchase_from_session,
    search_promo_products,
    start_plan,
)

ROOT = Path(__file__).resolve().parent / "static"
HOST = "127.0.0.1"
PORT = 8787

_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/meta":
            self._json(200, load_meta())
            return
        if path == "/api/stats":
            self._json(200, load_stats())
            return
        if path == "/api/stores":
            query = parse_qs(urlparse(self.path).query).get("query", [""])[0]
            self._json(200, list_shop_points(query))
            return
        if path == "/api/plan-job":
            job_id = parse_qs(urlparse(self.path).query).get("id", [""])[0]
            self._json(200, read_plan_job(job_id))
            return
        if path == "/api/promos":
            query = parse_qs(urlparse(self.path).query).get("shop_code", [""])[0]
            self._json(200, list_visible_promos(query))
            return
        if path in ("", "/"):
            path = "/index.html"
        self._file(path)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            body = self._body()
            if path == "/api/plan":
                payload = start_plan(
                    body.get("text"),
                    fake=bool(body.get("fake")),
                    shelf=bool(body.get("shelf")),
                    first_order=bool(body.get("first_order")),
                    delivery=_optional_float(body.get("delivery")),
                    again=bool(body.get("again")),
                    picks=_picks(body.get("picks")),
                    shop_code=str(body.get("shop_code") or body.get("store") or ""),
                    manual=bool(body.get("manual")),
                    promo=body.get("promo") if isinstance(body.get("promo"), dict) else None,
                )
            elif path == "/api/plan-job":
                promo = body.get("promo")
                payload = {
                    "job": queue_plan(
                        body.get("text"),
                        shop_code=str(body.get("shop_code") or body.get("store") or ""),
                        manual=bool(body.get("manual")),
                        promo=promo if isinstance(promo, dict) else None,
                    )
                }
            elif path == "/api/promo-products":
                payload = {
                    "products": search_promo_products(
                        str(body.get("shop_code") or ""),
                        str(body.get("text") or ""),
                    )
                }
            elif path == "/api/recalc":
                token = str(body.get("token") or "")
                payload = recalculate(
                    token,
                    picks=_picks(body.get("picks")),
                    delivery=_optional_float(body.get("delivery")),
                    counts=_counts(body.get("counts")),
                    store=str(body.get("store") or "") or None,
                    promo=body.get("promo") if isinstance(body.get("promo"), dict) else None,
                    replace_promo="promo" in body,
                )
            elif path == "/api/buy":
                payload = record_purchase_from_session(
                    str(body.get("token") or ""),
                    paid=_optional_float(body.get("paid")),
                    picks=_picks(body.get("picks")),
                    delivery=_optional_float(body.get("delivery")),
                )
            else:
                self._json(404, {"error": "Нет такого адреса"})
                return
        except PlanError as exc:
            self._json(exc.status, {"error": str(exc)})
            return
        except json.JSONDecodeError:
            self._json(400, {"error": "Не JSON"})
            return
        self._json(200, payload)

    def _file(self, path: str) -> None:
        relative = path.lstrip("/")
        file_path = (ROOT / relative).resolve()
        if not str(file_path).startswith(str(ROOT.resolve())) or not file_path.is_file():
            self._json(404, {"error": "Файл не найден"})
            return
        data = file_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", _TYPES.get(file_path.suffix, "application/octet-stream"))
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or "0")
        if length > 100_000:
            raise PlanError("Слишком большой запрос")
        raw = self.rfile.read(length) if length else b"{}"
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            raise PlanError("Жду объект JSON")
        return data

    def _json(self, status: int, payload: dict) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt: str, *args) -> None:
        print(f"[site] {self.address_string()} {fmt % args}")


def _optional_float(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise PlanError("Нужно число") from exc


def _picks(value: object) -> dict[str, str]:
    if not value:
        return {}
    if not isinstance(value, dict):
        raise PlanError("Выбор товаров передан не объектом")
    return {str(key): str(item) for key, item in value.items() if item is not None}


def _counts(value: object) -> dict[str, int] | None:
    if not value:
        return None
    if not isinstance(value, dict):
        raise PlanError("Количество передано не объектом")
    counts: dict[str, int] = {}
    for key, item in value.items():
        try:
            counts[str(key)] = int(item)
        except (TypeError, ValueError) as exc:
            raise PlanError(f"Количество для «{key}» — не число") from exc
    return counts


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Сайт: http://{HOST}:{PORT}")
    print("Остановка: Ctrl+C")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nОстановлен.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
