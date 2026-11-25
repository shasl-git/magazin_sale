"""Базовый интерфейс парсера → нормализованный Offer."""

from __future__ import annotations

from abc import ABC, abstractmethod

from domain.models import Offer, Promo


class BaseParser(ABC):
    store: str

    @abstractmethod
    def search(self, query: str) -> list[Offer]:
        """Поиск по строке («молоко») → список офферов с ценой и наличием."""

    def fetch_promos(self) -> list[Promo]:
        """Корзинные акции. На MVP можно возвращать [] и заводить вручную."""
        return []
