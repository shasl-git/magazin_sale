"""Матчинг: свободный текст → need + запоминание alias после выбора пользователя."""

from __future__ import annotations

import re

# Простые синонимы для v1 (не угадываем бренды — только нормализация запроса)
_SYNONYMS: dict[str, str] = {
    "кола": "кола",
    "кока-кола": "кола",
    "coca-cola": "кола",
    "coca cola": "кола",
    "напиток кола": "кола",
    "чипсы": "чипсы",
    "лейс": "чипсы",
    "lays": "чипсы",
    "молоко": "молоко",
    "хлеб": "хлеб",
    "сахар": "сахар",
    "чокопай": "чокопай",
    "чоко пай": "чокопай",
}


def normalize_need(raw: str) -> str:
    text = " ".join(raw.strip().lower().split())
    return _SYNONYMS.get(text, text)


def parse_list(text: str) -> list[str]:
    """Имена нужд без повторов. Количество см. parse_items."""
    return [need for need, _count in parse_items(text)]


def parse_items(text: str) -> list[tuple[str, int]]:
    """«молоко x2, 3 x яйца, сахар 2 шт». Повтор без количества не удваивает."""
    items: list[tuple[str, int]] = []
    index: dict[str, int] = {}
    for chunk in text.replace("\n", ",").split(","):
        need, count, explicit = _split_count(chunk)
        if not need:
            continue
        if need in index:
            if explicit:
                pos = index[need]
                prev_name, prev_count = items[pos]
                items[pos] = (prev_name, min(prev_count + count, 30))
            continue
        index[need] = len(items)
        items.append((need, count))
    return items


def _split_count(raw: str) -> tuple[str, int, bool]:
    text = " ".join(raw.strip().lower().split())
    if not text:
        return "", 1, False
    patterns = (
        r"^(\d+)\s*[xх×*]\s*(.+)$",
        r"^(\d+)\s*шт\s+(.+)$",
        r"^(.+?)\s*[xх×*]\s*(\d+)$",
        r"^(.+?)\s+(\d+)\s*шт$",
    )
    for pattern in patterns:
        match = re.match(pattern, text)
        if match is None:
            continue
        left, right = match.group(1), match.group(2)
        if left.isdigit():
            return normalize_need(right), _bounded_count(left), True
        return normalize_need(left), _bounded_count(right), True
    return normalize_need(text), 1, False


def _bounded_count(raw: str) -> int:
    value = int(raw)
    if value < 1:
        return 1
    return min(value, 30)


def remember_alias(
    aliases: dict[tuple[str, str], str],
    need: str,
    store: str,
    external_sku: str,
) -> dict[tuple[str, str], str]:
    """
    Пользователь нажал «это оно» → запомнить.
    Ключ: (need, store) → external_sku.
    """
    updated = dict(aliases)
    updated[(normalize_need(need), store)] = external_sku
    return updated
