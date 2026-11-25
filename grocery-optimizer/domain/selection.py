"""Выбор SKU: номера из списка вариантов и запомненный «это оно»."""

from __future__ import annotations

from .matching import normalize_need
from .models import Offer
from .optimizer import compare_sku

# Сколько вариантов показывать и принимать в --sku. Номера в плане = номера здесь.
SKU_SHOW = 8


class PickError(ValueError):
    """Непонятный номер или название в --sku."""


def ranked_choices(
    offers: list[Offer],
    needs: list[str],
    store: str,
    *,
    limit: int = SKU_SHOW,
) -> dict[str, list[tuple[Offer, str]]]:
    """Варианты одной нужды в одном магазине, выгодные за единицу — первыми."""
    ranked: dict[str, list[tuple[Offer, str]]] = {}
    for need in needs:
        variants = [o for o in offers if o.need == need and o.store == store]
        options = compare_sku(variants, limit=limit)
        if options:
            ranked[need] = options
    return ranked


def parse_sku_spec(spec: str, needs: list[str]) -> dict[str, int]:
    """
    Разобрать выбор.

    «2,1» — номера по порядку списка (1 = самый выгодный за единицу).
    «-» или «0» — оставить рекомендацию на этой позиции.
    «молоко=2, хлеб=1» — по названию нужды.
    """
    raw_tokens = [part.strip() for part in spec.split(",")]
    while raw_tokens and raw_tokens[-1] == "":
        raw_tokens.pop()
    if not raw_tokens or all(token == "" for token in raw_tokens):
        raise PickError("Пустой --sku. Пример: --sku \"2,1\" или --sku \"молоко=2\"")

    if any("=" in token for token in raw_tokens):
        return _parse_named(raw_tokens, needs)
    if len(raw_tokens) > len(needs):
        raise PickError(
            f"В --sku {len(raw_tokens)} номеров, в списке {len(needs)} позиций"
        )
    indexes: dict[str, int] = {}
    for need, token in zip(needs, raw_tokens):
        if _is_skip(token):
            continue
        indexes[need] = _parse_index(token)
    return indexes


def pick_offers(
    ranked: dict[str, list[tuple[Offer, str]]],
    indexes: dict[str, int],
) -> dict[str, Offer]:
    """Номер 1..N внутри уже отранжированного списка."""
    selected: dict[str, Offer] = {}
    for need, index in indexes.items():
        options = ranked.get(need) or []
        if not options:
            raise PickError(f"Нет вариантов в наличии: {need}")
        if index > len(options):
            raise PickError(
                f"«{need}»: номер {index}, в списке только {len(options)}"
            )
        selected[need] = options[index - 1][0]
    return selected


def overlay_preferred(
    offers: list[Offer],
    selected: dict[str, Offer] | None,
    preferred: dict[tuple[str, str], str],
) -> dict[str, Offer]:
    """Подставить запомненный SKU, если он ещё есть в наличии."""
    updated = dict(selected or {})
    for (need, store), sku in preferred.items():
        match = next(
            (
                offer
                for offer in offers
                if offer.need == need
                and offer.store == store
                and offer.external_id == sku
                and offer.in_stock
            ),
            None,
        )
        if match is not None:
            updated[need] = match
    return updated


def _parse_named(tokens: list[str], needs: list[str]) -> dict[str, int]:
    indexes: dict[str, int] = {}
    known = set(needs)
    for token in tokens:
        if token == "":
            raise PickError("Лишняя запятая в --sku")
        if "=" not in token:
            raise PickError(
                f"Смешаны форматы. Либо «2,1», либо «молоко=2». Сейчас: {token}"
            )
        name, _, number = token.partition("=")
        need = normalize_need(name)
        if need not in known:
            raise PickError(f"В списке нет «{need}»")
        if _is_skip(number.strip()):
            continue
        indexes[need] = _parse_index(number.strip())
    return indexes


def _is_skip(token: str) -> bool:
    return token in {"", "-", "0"}


def _parse_index(raw: str) -> int:
    if not raw.isdigit():
        raise PickError(f"Не номер варианта: {raw}")
    value = int(raw)
    if value < 1:
        raise PickError(f"Номер варианта с 1, получено {value}")
    return value
