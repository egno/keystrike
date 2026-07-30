from collections.abc import Iterator
from typing import Protocol

from .daily_learn import DailyLearnBudget
from .markov import TransitionTable
from .models import (
    KeyStats,
    Keystroke,
    Layout,
    LayoutAggregates,
    SessionResult,
    Settings,
    SyncStatusReport,
)


class Clock(Protocol):
    def now_ns(self) -> int: ...
    def wall_epoch(self) -> float: ...


class IdGenerator(Protocol):
    def new_id(self) -> str: ...


class SessionRepository(Protocol):
    def append_keystroke(self, session_id: str, started_at: float, k: Keystroke) -> None: ...
    def save_header(self, header: SessionResult) -> None: ...
    def iter_headers(self, layout: str) -> Iterator[SessionResult]: ...
    def iter_all_headers(self) -> Iterator[SessionResult]: ...
    def load_keystrokes(self, session_id: str) -> Iterator[Keystroke]: ...


class SettingsRepository(Protocol):
    def load(self) -> Settings: ...
    def save(self, settings: Settings) -> None: ...


class LayoutRepository(Protocol):
    def list_available(self) -> list[str]: ...
    def get(self, name: str) -> Layout: ...


class AggregatesCache(Protocol):
    def get(self, layout: str) -> LayoutAggregates | None: ...
    def put(self, layout: str, aggregates: LayoutAggregates) -> None: ...


class StatsRebuilder(Protocol):
    """Shape of `application.stats_use_cases.RebuildAggregates` — lets callers
    (e.g. PracticeScreen) depend on the behavior without importing application code."""

    def __call__(self, layout: str) -> dict[int, KeyStats]: ...

    def ensure(self, layout: str) -> dict[int, KeyStats]: ...


class LanguageProvider(Protocol):
    def transitions(self, lang: str) -> TransitionTable: ...


class WordListStore(Protocol):
    def load(self, url: str) -> list[str] | None: ...
    def cached_word_count(self, url: str) -> int | None: ...
    def download_and_cache(self, url: str) -> list[str]: ...


class LearningRateEstimator(Protocol):
    """Shape of `application.stats_use_cases.GetLearningRate`."""

    def __call__(self, layout: str, codepoint: int) -> int | None: ...


class DailyLearnBudgetProvider(Protocol):
    """Shape of `application.learn_budget_use_cases.GetDailyLearnBudget`."""

    def __call__(self, *, extra_ns: int = 0) -> DailyLearnBudget: ...


class SyncStore(Protocol):
    """Shape of `infrastructure.sync_git.GitSyncGateway`."""

    def is_configured(self) -> bool: ...
    def init(self, remote_url: str) -> None: ...
    def pull(self, rebuild: StatsRebuilder) -> int: ...
    def push(self) -> bool: ...
    def status(self) -> SyncStatusReport: ...


class SyncGateway(SyncStore, Protocol):
    """Alias kept for application-layer typing."""
