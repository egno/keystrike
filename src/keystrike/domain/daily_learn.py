"""Daily adaptive (learn) mode time budget — pure functions only."""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable
from dataclasses import dataclass

from .enums import Mode
from .models import SessionResult

_NS_PER_MINUTE = 60 * 1_000_000_000


@dataclass(frozen=True, slots=True)
class DailyLearnBudget:
    limited: bool
    limit_ns: int
    used_ns: int
    remaining_ns: int
    limit_reached: bool


def session_local_date(started_at: float, tz: dt.tzinfo | None = None) -> dt.date:
    tz = tz or dt.datetime.now().astimezone().tzinfo or dt.UTC
    return dt.datetime.fromtimestamp(started_at, tz=tz).date()


def daily_learn_duration_ns(
    headers: Iterable[SessionResult],
    day: dt.date,
    *,
    tz: dt.tzinfo | None = None,
) -> int:
    tz = tz or dt.datetime.now().astimezone().tzinfo or dt.UTC
    total = 0
    for header in headers:
        if header.mode is not Mode.ADAPTIVE:
            continue
        if session_local_date(header.started_at, tz) != day:
            continue
        total += header.duration_ns
    return total


def format_daily_learn_display(budget: DailyLearnBudget, *, label: str) -> str:
    if not budget.limited:
        return ""
    limit_min = budget.limit_ns / 1e9 / 60
    if budget.limit_reached:
        return f"[dim]Daily learn goal reached ({limit_min:g} min).[/]"
    used_min = budget.used_ns / 1e9 / 60
    return f"{label} [bold]{used_min:.1f}[/]/{limit_min:g} min"


def compute_daily_learn_budget(
    *,
    completed_ns: int,
    limit_minutes: int,
    extra_ns: int = 0,
) -> DailyLearnBudget:
    used_ns = completed_ns + extra_ns
    if limit_minutes <= 0:
        return DailyLearnBudget(
            limited=False,
            limit_ns=0,
            used_ns=used_ns,
            remaining_ns=0,
            limit_reached=False,
        )
    limit_ns = limit_minutes * _NS_PER_MINUTE
    remaining_ns = max(0, limit_ns - used_ns)
    return DailyLearnBudget(
        limited=True,
        limit_ns=limit_ns,
        used_ns=used_ns,
        remaining_ns=remaining_ns,
        limit_reached=used_ns >= limit_ns,
    )
