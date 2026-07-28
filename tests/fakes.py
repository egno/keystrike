from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from itertools import count
from pathlib import Path

from keystrike.domain.markov import TransitionTable
from keystrike.domain.models import KeyStats, Keystroke, Layout, LayoutAggregates, SessionResult, Settings


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


@dataclass(slots=True)
class FakeFreeformTextProvider:
    text_by_path: dict[str, str] = field(default_factory=dict)

    def load(self, path: Path) -> str:
        return self.text_by_path[str(path)]


def _uniform_transition_table() -> TransitionTable:
    letters = "etaoinshrdlcumwfgypbvkjxqz"
    return TransitionTable(order=2, transitions={"": {ch: 1 for ch in letters}})


@dataclass(slots=True)
class FakeLanguageProvider:
    table: TransitionTable = field(default_factory=_uniform_transition_table)

    def transitions(self, lang: str) -> TransitionTable:
        _ = lang
        return self.table


def _default_snippets() -> tuple[str, ...]:
    return ("def add(a, b): return a + b", "for i in range(10): print(i)")


@dataclass(slots=True)
class FakeCodeSnippetProvider:
    snippets_: tuple[str, ...] = field(default_factory=_default_snippets)

    def snippets(self) -> tuple[str, ...]:
        return self.snippets_
