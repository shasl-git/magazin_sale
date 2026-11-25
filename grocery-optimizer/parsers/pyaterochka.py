"""Парсер Пятёрочки. Нужен sapCode в config.STORES.pyaterochka_sap_code."""

from __future__ import annotations

from domain.models import Offer
from parsers.base import BaseParser


class PyaterochkaParser(BaseParser):
    store = "pyaterochka"

    def __init__(self, sap_code: str = "") -> None:
        self.sap_code = sap_code

    def search(self, query: str) -> list[Offer]:
        if not self.sap_code:
            raise RuntimeError(
                "Нет sapCode Пятёрочки. Открой 5ka.ru → магазин в Индустриальном → "
                "Network → /stores/{sapCode}/... → впиши в config.STORES.pyaterochka_sap_code"
            )
        # Этап 2: GET .../catalog/v3/stores/{sapCode}/search?q=...
        raise NotImplementedError("Живой API Пятёрочки — следующий этап")
