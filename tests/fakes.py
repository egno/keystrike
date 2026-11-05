from __future__ import annotations

import datetime as dt
from collections.abc import Collection, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from itertools import count
from typing import Any

from keystrike.domain.aggregate import tally_session
from keystrike.domain.ai_models import AiAnalysis, AiSettings
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
    tz: dt.tzinfo = dt.UTC

    def now_ns(self) -> int:
        return self.t_ns

    def wall_epoch(self) -> float:
        return self.wall

    def local_tzinfo(self) -> dt.tzinfo:
        return self.tz

    def advance(self, ns: int) -> None:
        self.t_ns += ns


def _new_counter() -> Iterator[int]:
    return count(1)


@dataclass(slots=True)
class FakeIdGenerator:
    _counter: Iterator[int] = field(default_factory=_new_counter)

    def new_id(self) -> str:
        return f"fake-{next(self._counter):06d}"


def _empty_headers() -> list[SessionResult]:
    return []


@dataclass(slots=True)
class FakeSessionRepository:
    headers: list[SessionResult] = field(default_factory=_empty_headers)

    def save_header(self, header: SessionResult) -> None:
        self.headers.append(header)

    def save_with_keystrokes(self, header: SessionResult, keystrokes: Iterable[Keystroke]) -> None:
        """Test convenience: store `header` with the stats `FinishSession`
        would have tallied from `keystrokes`."""
        self.headers.append(replace(header, stats=tally_session(keystrokes)))

    def iter_headers(self, layout: str) -> Iterator[SessionResult]:
        return iter(h for h in self.headers if h.layout == layout)

    def iter_all_headers(self) -> Iterator[SessionResult]:
        return iter(self.headers)

    def replace_all_headers(self, headers: Iterable[SessionResult]) -> None:
        self.headers = list(headers)


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


@dataclass(slots=True)
class FakeAiSettingsRepository:
    settings: AiSettings = field(default_factory=AiSettings)

    def load(self) -> AiSettings:
        return self.settings

    def save(self, settings: AiSettings) -> None:
        self.settings = settings


def _empty_analyses() -> dict[str, AiAnalysis]:
    return {}


@dataclass(slots=True)
class FakeAiAnalysisStore:
    by_layout: dict[str, AiAnalysis] = field(default_factory=_empty_analyses)

    def get(self, layout: str) -> AiAnalysis | None:
        return self.by_layout.get(layout)

    def put(self, analysis: AiAnalysis) -> None:
        self.by_layout[analysis.layout] = analysis

    def clear(self) -> None:
        self.by_layout.clear()


def _empty_streams() -> dict[str, list[Keystroke]]:
    return {}


@dataclass(slots=True)
class FakeKeystrokeArchive:
    saved: dict[str, list[Keystroke]] = field(default_factory=_empty_streams)
    error: Exception | None = None

    def save(self, session_id: str, keystrokes: Sequence[Keystroke]) -> None:
        if self.error is not None:
            raise self.error
        self.saved[session_id] = list(keystrokes)

    def load(self, session_ids: Sequence[str]) -> dict[str, list[Keystroke]]:
        return {sid: self.saved[sid] for sid in session_ids if sid in self.saved}

    def prune(self, keep: Collection[str]) -> None:
        self.saved = {sid: ks for sid, ks in self.saved.items() if sid in keep}

    def clear(self) -> None:
        self.saved.clear()


class FakeChat:
    """Scripted ChatClient: returns `reply` (or raises `error`) and records
    every request."""

    def __init__(self, reply: str = "", error: Exception | None = None) -> None:
        self.reply = reply
        self.error = error
        self.prompts: list[tuple[str, str]] = []
        self.schemas: list[Mapping[str, Any] | None] = []

    @property
    def calls(self) -> int:
        return len(self.prompts)

    async def chat(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        schema: Mapping[str, Any] | None = None,
    ) -> str:
        self.prompts.append((system_prompt, user_prompt))
        self.schemas.append(schema)
        if self.error is not None:
            raise self.error
        return self.reply
