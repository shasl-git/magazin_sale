"""Счётчик экономии: запись покупки и агрегации."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass
class SavingsEntry:
    bought_at: datetime
    store: str
    baseline_total: float
    calculated_total: float
    paid_total: float
    saved: float


@dataclass
class SavingsSummary:
    week: float
    month: float
    half_year: float
    year: float
    entries: list[SavingsEntry]


def compute_saved(baseline_total: float, paid_total: float) -> float:
    return round(max(0.0, baseline_total - paid_total), 2)


def record_purchase(
    *,
    baseline_total: float,
    calculated_total: float,
    paid_total: float | None,
    store: str,
    bought_at: datetime | None = None,
) -> SavingsEntry:
    paid = paid_total if paid_total is not None else calculated_total
    return SavingsEntry(
        bought_at=bought_at or datetime.now(),
        store=store,
        baseline_total=baseline_total,
        calculated_total=calculated_total,
        paid_total=paid,
        saved=compute_saved(baseline_total, paid),
    )


def saved_since_midnight(entries: list[SavingsEntry], *, now: datetime | None = None) -> float:
    now = now or datetime.now()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return round(sum(entry.saved for entry in entries if entry.bought_at >= start), 2)


def summarize(entries: list[SavingsEntry], *, now: datetime | None = None) -> SavingsSummary:
    now = now or datetime.now()

    def _sum_since(delta: timedelta) -> float:
        cutoff = now - delta
        return round(sum(e.saved for e in entries if e.bought_at >= cutoff), 2)

    return SavingsSummary(
        week=_sum_since(timedelta(days=7)),
        month=_sum_since(timedelta(days=30)),
        half_year=_sum_since(timedelta(days=182)),
        year=_sum_since(timedelta(days=365)),
        entries=sorted(entries, key=lambda e: e.bought_at, reverse=True),
    )
