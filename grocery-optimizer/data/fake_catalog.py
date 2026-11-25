"""Фейковый каталог для разработки алгоритма без парсеров."""

from __future__ import annotations

from domain.models import Offer, Promo

# Цены условные, Индустриальный район Барнаул — для тестов логики
FAKE_OFFERS: list[Offer] = [
    # молоко
    Offer("magnit", "молоко", "m-milk-1", "Простоквашино 1 л", 89.0, 110.0, "мл", 1000),
    Offer("magnit", "молоко", "m-milk-2", "Белый замок 1,2 л", 99.0, 115.0, "мл", 1200),
    Offer("magnit", "молоко", "m-milk-3", "Домик в деревне 0,9 л", 95.0, 105.0, "мл", 900),
    Offer("pyaterochka", "молоко", "p-milk-1", "Простоквашино 1 л", 92.0, 112.0, "мл", 1000),
    Offer("pyaterochka", "молоко", "p-milk-2", "Вкуснотеево 1 л", 85.0, 100.0, "мл", 1000),
    # хлеб
    Offer("magnit", "хлеб", "m-bread-1", "Хлеб дарницкий", 45.0, 52.0, "г", 650),
    Offer("magnit", "хлеб", "m-bread-2", "Батон нарезной", 42.0, 48.0, "г", 400),
    Offer("pyaterochka", "хлеб", "p-bread-1", "Хлеб дарницкий", 48.0, 55.0, "г", 650),
    Offer("pyaterochka", "хлеб", "p-bread-2", "Батон", 39.0, 45.0, "г", 400),
    # сахар
    Offer("magnit", "сахар", "m-sugar-1", "Сахар песок 1 кг", 79.0, 89.0, "г", 1000),
    Offer("pyaterochka", "сахар", "p-sugar-1", "Сахар песок 1 кг", 74.0, 85.0, "г", 1000),
    # чипсы
    Offer("magnit", "чипсы", "m-chips-1", "Lays 140 г", 129.0, 159.0, "г", 140),
    Offer("magnit", "чипсы", "m-chips-2", "Русская картошка 150 г", 99.0, 119.0, "г", 150),
    Offer("pyaterochka", "чипсы", "p-chips-1", "Lays 140 г", 119.0, 149.0, "г", 140),
    Offer("pyaterochka", "чипсы", "p-chips-2", "Чипсоны 100 г", 69.0, 89.0, "г", 100),
    # кола
    Offer("magnit", "кола", "m-cola-1", "Coca-Cola 1 л", 119.0, 139.0, "мл", 1000),
    Offer("magnit", "кола", "m-cola-2", "Cola 2 л", 149.0, 179.0, "мл", 2000),
    Offer("pyaterochka", "кола", "p-cola-1", "Coca-Cola 1 л", 109.0, 135.0, "мл", 1000),
    Offer("pyaterochka", "кола", "p-cola-2", "Добрый Кола 2 л", 139.0, 169.0, "мл", 2000),
    # добивка до порога
    Offer("magnit", "добивка", "m-top-1", "Чокопай Orion 6 шт", 89.0, 119.0, "шт", 6),
    Offer("magnit", "добивка", "m-top-2", "Печенье Юбилейное", 65.0, 79.0, "г", 268),
    Offer("pyaterochka", "добивка", "p-top-1", "Шоколад Alpen Gold", 89.0, 109.0, "г", 90),
]

FAKE_PROMOS: list[Promo] = [
    Promo("magnit", "cart_threshold", "−20% от 1000 ₽", threshold=1000, discount_value=0.20, discount_kind="percent"),
    Promo("magnit", "free_delivery", "Доставка бесплатно от 1000 ₽", threshold=1000),
    Promo("pyaterochka", "cart_threshold", "−300 ₽ от 1500 ₽", threshold=1500, discount_value=300, discount_kind="amount"),
    Promo("pyaterochka", "free_delivery", "Доставка бесплатно от 1500 ₽", threshold=1500),
]
