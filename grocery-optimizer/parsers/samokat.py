"""Самокат — третьим. Пока заглушка."""

from __future__ import annotations

from domain.models import Offer
from parsers.base import BaseParser


class SamokatParser(BaseParser):
    store = "samokat"

    def search(self, query: str) -> list[Offer]:
        raise NotImplementedError("Самокат — после Магнита и Пятёрочки")
