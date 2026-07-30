"""Null Object implementations of domain protocols.

Stand-ins for optional collaborators so use cases and screens can depend on a
required protocol value instead of `X | None` plus scattered `is not None`
checks. Each one is inert (no I/O, no state) so keeping it in `domain/` does
not violate the "domain has no I/O" rule.
"""

from __future__ import annotations

from collections.abc import Iterator

from .daily_learn import DailyLearnBudget, compute_daily_learn_budget
from .models import KeyStats, Keystroke, Layout, SessionResult, Settings


class NullSessionRepository:
    def append_keystroke(self, session_id: str, started_at: float, k: Keystroke) -> None:
        pass

    def save_header(self, header: SessionResult) -> None:
        pass

    def iter_headers(self, layout: str) -> Iterator[SessionResult]:
        return iter(())

    def iter_all_headers(self) -> Iterator[SessionResult]:
        return iter(())

    def load_keystrokes(self, session_id: str) -> Iterator[Keystroke]:
        return iter(())


class NullStatsRebuilder:
    def __call__(self, layout: str) -> None:
        return None


NULL_STATS_REBUILDER = NullStatsRebuilder()


class NullAggregatesEnsurer:
    def __call__(self, layout: str) -> dict[int, KeyStats]:
        return {}


NULL_AGGREGATES_ENSURER = NullAggregatesEnsurer()


class NullLearningRateEstimator:
    def __call__(self, layout: str, codepoint: int) -> int | None:
        return None


NULL_LEARNING_RATE_ESTIMATOR = NullLearningRateEstimator()


class NullDailyLearnBudgetProvider:
    def __call__(self, *, extra_ns: int = 0) -> DailyLearnBudget:
        return compute_daily_learn_budget(completed_ns=0, limit_minutes=0, extra_ns=extra_ns)


NULL_DAILY_LEARN_BUDGET = NullDailyLearnBudgetProvider()


class NullSettingsRepository:
    """Inert stand-in when no persisted Settings should be read or written —
    load() returns the plain defaults, save() discards."""

    def load(self) -> Settings:
        return Settings()

    def save(self, settings: Settings) -> None:
        pass


NULL_SETTINGS_REPOSITORY = NullSettingsRepository()


class NullLayoutRepository:
    """Inert stand-in when no real layout should be read — an empty layout
    with no keys/learn_order, so downstream key-unlock math sees nothing to
    unlock instead of raising."""

    def list_available(self) -> list[str]:
        return []

    def get(self, name: str) -> Layout:
        return Layout(name=name, keys={}, learn_order=())


NULL_LAYOUT_REPOSITORY = NullLayoutRepository()
