"""Конфиг личного MVP: Барнаул, один магазин за закупку."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "db" / "app.db"


@dataclass
class StoreIds:
    """Внешние id точек. Магнит: python -m tools.find_stores"""

    magnit_store_code: str = "084788"  # shopCode; заполняется tools.find_stores
    pyaterochka_sap_code: str = ""  # sapCode с 5ka.ru (позже)
    samokat_zone_id: str = ""  # позже


@dataclass
class UserPrefs:
    city: str = "Барнаул"
    district: str = "Индустриальный район"
    # Только один магазин за закупку (без разбиения на 2 доставки)
    single_store_only: bool = True
    delivery_cost_default: float = 500.0
    has_loyalty_card: bool = True
    # Тестовый список для разработки
    sample_list: list[str] = field(
        default_factory=lambda: ["молоко", "хлеб", "сахар", "чипсы", "кола"]
    )


STORES = StoreIds()
USER = UserPrefs()

# Кэш офферов, часов
OFFER_CACHE_HOURS = 3

# Магазины v1 (Самокат — третьим)
ACTIVE_STORES = ("magnit", "pyaterochka")
