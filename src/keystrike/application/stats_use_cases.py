"""Use cases for rebuilding and reading per-layout key-stats aggregates."""

from __future__ import annotations

import time
from dataclasses import dataclass

from keystrike.domain.aggregate import combine_sessions, per_key_deltas
from keystrike.domain.confidence import (
    confidence_of,
    review_urgency,
    target_ms_per_char,
)
from keystrike.domain.models import KeyStats, SessionResult
from keystrike.domain.protocols import AggregatesCache, SessionRepository, SettingsRepository
from keystrike.domain.regression import estimate_sessions_to_goal

_NS_PER_MS = 1e6


@dataclass(slots=True)
class RebuildAggregates:
    """Replay the last N sessions (from settings) into the cache."""

    repo: SessionRepository
    cache: AggregatesCache
    settings_repo: SettingsRepository

    def __call__(self, layout: str) -> dict[int, KeyStats]:
        window = self.settings_repo.load().confidence_session_window
        headers = sorted(
            self.repo.iter_headers(layout),
            key=lambda h: h.started_at,
        )[-window:]
        combined = combine_sessions(
            [(header, self.repo.load_keystrokes(header.session_id)) for header in headers],
        )
        self.cache.put(layout, combined)
        return combined.keys


@dataclass(frozen=True, slots=True)
class HeatmapView:
    confidence: dict[int, float]
    urgency: dict[int, float]


@dataclass(slots=True)
class GetHeatmap:
    """Confidence and review-urgency per key. Reads the cache as-is."""

    cache: AggregatesCache
    settings_repo: SettingsRepository

    def __call__(self, layout: str) -> HeatmapView:
        aggregates = self.cache.get(layout)
        if not aggregates:
            return HeatmapView(confidence={}, urgency={})
        stats = aggregates.keys
        settings = self.settings_repo.load()
        target = target_ms_per_char(settings.target_speed_cpm)
        now = time.time()
        return HeatmapView(
            confidence={
                cp: confidence_of(
                    cp,
                    stats,
                    target,
                    min_attempts=settings.min_confidence_attempts,
                )
                for cp in stats
            },
            urgency={cp: review_urgency(k.last_seen, now) for cp, k in stats.items()},
        )


@dataclass(slots=True)
class GetHistory:
    """Most-recent sessions for a layout, newest first."""

    repo: SessionRepository

    def __call__(self, layout: str, limit: int = 20) -> list[SessionResult]:
        headers = sorted(self.repo.iter_headers(layout), key=lambda h: h.started_at, reverse=True)
        return headers[:limit]


@dataclass(slots=True)
class GetLearningRate:
    """Sessions-to-goal estimate for one key: fit a curve to its most recent
    per-attempt timings (across the last few sessions) and see how many more
    attempts, at the observed trend, until it reaches the target speed."""

    repo: SessionRepository
    settings_repo: SettingsRepository

    def __call__(self, layout: str, codepoint: int, max_sessions: int = 10) -> int | None:
        target_ns = target_ms_per_char(self.settings_repo.load().target_speed_cpm) * _NS_PER_MS
        headers = sorted(self.repo.iter_headers(layout), key=lambda h: h.started_at)
        recent_headers = headers[-max_sessions:]

        samples: list[float] = []
        for header in recent_headers:
            deltas = per_key_deltas(self.repo.load_keystrokes(header.session_id))
            samples.extend(deltas.get(codepoint, []))

        return estimate_sessions_to_goal(samples, target_ns)
