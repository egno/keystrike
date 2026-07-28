"""Null Object implementations of domain protocols.

Stand-ins for optional collaborators so use cases and screens can depend on a
required protocol value instead of `X | None` plus scattered `is not None`
checks. Each one is inert (no I/O, no state) so keeping it in `domain/` does
not violate the "domain has no I/O" rule.
"""

from __future__ import annotations

from collections.abc import Iterator

from .models import KeyStats, Keystroke, SessionResult


class NullSessionRepository:
    def append_keystroke(self, session_id: str, started_at: float, k: Keystroke) -> None:
        pass

    def save_header(self, header: SessionResult) -> None:
        pass

    def iter_headers(self, layout: str) -> Iterator[SessionResult]:
        return iter(())

    def load_keystrokes(self, session_id: str) -> Iterator[Keystroke]:
        return iter(())


class NullStatsRebuilder:
    def __call__(self, layout: str) -> dict[int, KeyStats]:
        return {}


NULL_STATS_REBUILDER = NullStatsRebuilder()


class NullLearningRateEstimator:
    def __call__(self, layout: str, codepoint: int) -> int | None:
        return None


NULL_LEARNING_RATE_ESTIMATOR = NullLearningRateEstimator()
