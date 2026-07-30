"""Use cases for the daily adaptive (learn) mode time budget."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from keystrike.domain.daily_learn import (
    DailyLearnBudget,
    compute_daily_learn_budget,
    daily_learn_duration_ns,
    session_local_date,
)
from keystrike.domain.protocols import Clock, SessionRepository, SettingsRepository


@dataclass(slots=True)
class GetDailyLearnBudget:
    clock: Clock
    repo: SessionRepository
    settings_repo: SettingsRepository
    tz: dt.tzinfo | None = None

    def __call__(self, *, extra_ns: int = 0) -> DailyLearnBudget:
        tz = self.tz or self.clock.local_tzinfo()
        today = session_local_date(self.clock.wall_epoch(), tz)
        completed_ns = daily_learn_duration_ns(self.repo.iter_all_headers(), today, tz=tz)
        limit_minutes = self.settings_repo.load().learn_daily_minutes
        return compute_daily_learn_budget(
            completed_ns=completed_ns,
            limit_minutes=limit_minutes,
            extra_ns=extra_ns,
        )
