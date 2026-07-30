from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from itertools import count

from keystrike.domain.markov import TransitionTable
from keystrike.domain.models import (
    Keystroke,
    Layout,
    LayoutAggregates,
    SessionResult,
    Settings,
    SyncStatusReport,
)
from keystrike.domain.protocols import StatsRebuilder


@dataclass(slots=True)
class FakeClock:
    """Deterministic clock. `advance(ns)` moves it forward."""

    t_ns: int = 0
    wall: float = 1_700_000_000.0

    def now_ns(self) -> int:
        return self.t_ns

    def wall_epoch(self) -> float:
        return self.wall

    def advance(self, ns: int) -> None:
        self.t_ns += ns


def _new_counter() -> Iterator[int]:
    return count(1)


@dataclass(slots=True)
class FakeIdGenerator:
    _counter: Iterator[int] = field(default_factory=_new_counter)

    def new_id(self) -> str:
        return f"fake-{next(self._counter):06d}"


def _empty_keystrokes() -> dict[str, list[Keystroke]]:
    return {}


def _empty_headers() -> list[SessionResult]:
    return []


@dataclass(slots=True)
class FakeSessionRepository:
    keystrokes: dict[str, list[Keystroke]] = field(default_factory=_empty_keystrokes)
    headers: list[SessionResult] = field(default_factory=_empty_headers)

    def append_keystroke(self, session_id: str, started_at: float, k: Keystroke) -> None:
        _ = started_at  # not used by the fake, but keeps protocol shape
        self.keystrokes.setdefault(session_id, []).append(k)

    def append_keystrokes(
        self, session_id: str, started_at: float, keystrokes: Iterable[Keystroke]
    ) -> None:
        _ = started_at  # not used by the fake, but keeps protocol shape
        self.keystrokes.setdefault(session_id, []).extend(keystrokes)

    def save_header(self, header: SessionResult) -> None:
        self.headers.append(header)

    def iter_headers(self, layout: str) -> Iterator[SessionResult]:
        return iter(h for h in self.headers if h.layout == layout)

    def iter_all_headers(self) -> Iterator[SessionResult]:
        return iter(self.headers)

    def load_keystrokes(self, session_id: str) -> Iterator[Keystroke]:
        return iter(self.keystrokes.get(session_id, []))


def _empty_aggregates() -> dict[str, LayoutAggregates]:
    return {}


@dataclass(slots=True)
class FakeAggregatesCache:
    by_layout: dict[str, LayoutAggregates] = field(default_factory=_empty_aggregates)

    def get(self, layout: str) -> LayoutAggregates | None:
        return self.by_layout.get(layout)

    def put(self, layout: str, aggregates: LayoutAggregates) -> None:
        self.by_layout[layout] = aggregates


@dataclass(slots=True)
class FakeSettingsRepository:
    settings: Settings = field(default_factory=Settings)

    def load(self) -> Settings:
        return self.settings

    def save(self, settings: Settings) -> None:
        self.settings = settings


@dataclass(slots=True)
class FakeLayoutRepository:
    layouts: dict[str, Layout]

    def list_available(self) -> list[str]:
        return sorted(self.layouts)

    def get(self, name: str) -> Layout:
        return self.layouts[name]


def _uniform_transition_table() -> TransitionTable:
    letters = "etaoinshrdlcumwfgypbvkjxqz"
    return TransitionTable(order=2, transitions={"": {ch: 1 for ch in letters}})


@dataclass(slots=True)
class FakeLanguageProvider:
    table: TransitionTable = field(default_factory=_uniform_transition_table)

    def transitions(self, lang: str) -> TransitionTable:
        _ = lang
        return self.table


@dataclass(slots=True)
class FakeWordListStore:
    by_url: dict[str, list[str]] = field(default_factory=dict)
    download_error: Exception | None = None

    def load(self, url: str) -> list[str] | None:
        words = self.by_url.get(url)
        return list(words) if words is not None else None

    def cached_word_count(self, url: str) -> int | None:
        words = self.load(url)
        return len(words) if words is not None else None

    def download_and_cache(self, url: str) -> list[str]:
        if self.download_error is not None:
            raise self.download_error
        if url in self.by_url:
            return list(self.by_url[url])
        raise ValueError("download failed")


@dataclass(slots=True)
class FakeSyncStore:
    """Deterministic stand-in for `infrastructure.sync_git.GitSyncGateway`.

    `pulled_layouts` names the layouts `pull()` should invoke `rebuild` for
    (simulating new sessions arriving from the remote for those layouts);
    `pull_result`/`push_result` control the return values.
    """

    configured: bool = False
    remote_url: str | None = None
    pulled_layouts: list[str] = field(default_factory=list)
    pull_result: int = 0
    push_result: bool = True
    status_report: SyncStatusReport | None = None
    init_calls: list[str] = field(default_factory=list)
    rebuilt_layouts: list[str] = field(default_factory=list)

    def is_configured(self) -> bool:
        return self.configured

    def init(self, remote_url: str) -> None:
        self.configured = True
        self.remote_url = remote_url
        self.init_calls.append(remote_url)

    def pull(self, rebuild: StatsRebuilder) -> int:
        for layout in self.pulled_layouts:
            rebuild(layout)
            self.rebuilt_layouts.append(layout)
        return self.pull_result

    def push(self) -> bool:
        return self.push_result

    def status(self) -> SyncStatusReport:
        if self.status_report is not None:
            return self.status_report
        return SyncStatusReport(
            configured=self.configured,
            remote_url=self.remote_url,
            git_status="clean",
            local_sessions=0,
            clone_sessions=0,
            only_local=0,
            only_clone=0,
        )
