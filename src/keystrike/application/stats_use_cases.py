"""Use cases for rebuilding and reading per-layout key-stats aggregates."""

from __future__ import annotations

from dataclasses import dataclass, replace

from keystrike.domain.aggregate import aggregate_session, combine, per_key_deltas
from keystrike.domain.confidence import accuracy_of, key_confidence, target_ms_per_char
from keystrike.domain.models import KeyStats, SessionResult
from keystrike.domain.protocols import AggregatesCache, SessionRepository, SettingsRepository
from keystrike.domain.regression import estimate_sessions_to_goal

_NS_PER_MS = 1e6


@dataclass(slots=True)
class RebuildAggregates:
    """Replay every stored session for a layout into a fresh KeyStats cache entry.

    Also (re)stamps `peak_confidence` on each per-session slice — evaluated
    against today's target speed — before combining, so `combine()`'s max()
    tracks the best single-session confidence ever recorded for that key.
    This is what `recover_keys=True` reads in the M3 adaptive engine.
    """

    repo: SessionRepository
    cache: AggregatesCache
    settings_repo: SettingsRepository

    def __call__(self, layout: str) -> dict[int, KeyStats]:
        target = target_ms_per_char(self.settings_repo.load().target_speed_cpm)
        maps = [
            _stamp_peak_confidence(
                aggregate_session(header, self.repo.load_keystrokes(header.session_id)), target,
            )
            for header in self.repo.iter_headers(layout)
        ]
        combined = combine(*maps)
        self.cache.put(layout, combined)
        return combined


def _stamp_peak_confidence(stats: dict[int, KeyStats], target: float) -> dict[int, KeyStats]:
    return {
        cp: replace(k, peak_confidence=key_confidence(target, k.mean_time_ns) * accuracy_of(k))
        for cp, k in stats.items()
    }


@dataclass(slots=True)
class GetHeatmap:
    """Confidence per key: target_ms_per_char / mean_ms_per_key. Reads the cache as-is."""

    cache: AggregatesCache
    settings_repo: SettingsRepository

    def __call__(self, layout: str) -> dict[int, float]:
        stats = self.cache.get(layout)
        if not stats:
            return {}
        target = target_ms_per_char(self.settings_repo.load().target_speed_cpm)
        return {
            cp: key_confidence(target, k.mean_time_ns) * accuracy_of(k) for cp, k in stats.items()
        }


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
