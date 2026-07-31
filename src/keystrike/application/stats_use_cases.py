"""Use cases for rebuilding and reading per-layout key-stats aggregates."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from typing import NamedTuple

from keystrike.domain.aggregate import combine_sessions
from keystrike.domain.confidence import (
    accuracy_of,
    confidence_of,
    key_attempts,
    key_confidence,
    review_urgency,
    round_confidence,
    target_ms_per_char,
)
from keystrike.domain.models import KeyStats, SessionResult
from keystrike.domain.protocols import (
    AggregatesCache,
    Clock,
    SessionRepository,
    SettingsRepository,
)

_NS_PER_MS = 1e6


class SessionMetrics(NamedTuple):
    """Per-session metrics: speed confidence, accuracy, and overall confidence."""

    speed: float
    accuracy: float
    confidence: float


@dataclass(slots=True)
class RebuildAggregates:
    """Command: replay the last N sessions (from settings) into the cache."""

    repo: SessionRepository
    cache: AggregatesCache
    settings_repo: SettingsRepository

    def __call__(self, layout: str) -> None:
        window = self.settings_repo.load().confidence_session_window
        headers = sorted(
            self.repo.iter_headers(layout),
            key=lambda h: h.started_at,
        )[-window:]
        combined = combine_sessions(
            [(header, self.repo.load_keystrokes(header.session_id)) for header in headers],
        )
        self.cache.put(layout, combined)


@dataclass(slots=True)
class GetOrRebuildAggregates:
    """Query: current per-key aggregates for a layout.

    Rebuilds first (via ``rebuild``) only when the cache is missing or lacks
    transitions despite session history — callers never have to decide
    whether a rebuild is needed themselves.
    """

    repo: SessionRepository
    cache: AggregatesCache
    rebuild: RebuildAggregates

    def __call__(self, layout: str) -> Mapping[int, KeyStats]:
        cached = self.cache.get(layout)
        has_sessions = any(self.repo.iter_headers(layout))
        if cached is not None:
            if cached.transitions or cached.transitions_computed or not has_sessions:
                return cached.keys
            self.rebuild(layout)
            rebuilt = self.cache.get(layout)
            return rebuilt.keys if rebuilt is not None else {}
        if not has_sessions:
            return {}
        self.rebuild(layout)
        rebuilt = self.cache.get(layout)
        return rebuilt.keys if rebuilt is not None else {}


@dataclass(frozen=True, slots=True)
class HeatmapView:
    confidence: dict[int, float]
    urgency: dict[int, float]


@dataclass(slots=True)
class GetHeatmap:
    """Confidence and review-urgency per key. Reads the cache as-is."""

    cache: AggregatesCache
    settings_repo: SettingsRepository
    clock: Clock

    def __call__(self, layout: str) -> HeatmapView:
        aggregates = self.cache.get(layout)
        if not aggregates:
            return HeatmapView(confidence={}, urgency={})
        stats = aggregates.keys
        settings = self.settings_repo.load()
        target = target_ms_per_char(settings.target_speed_cpm)
        now = self.clock.wall_epoch()
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


def _normalize_speed_to_current_goal(
    speed: float,
    stored_target_cpm: int,
    current_target_cpm: int,
) -> float:
    if stored_target_cpm <= 0 or current_target_cpm <= 0:
        return speed
    return speed * (target_ms_per_char(current_target_cpm) / target_ms_per_char(stored_target_cpm))


def _aggregate_speed_accuracy(
    stats: Mapping[int, KeyStats],
    target_ms: float,
) -> tuple[float, float]:
    total_samples = 0
    total_errors = 0
    weighted_time = 0.0
    for key_stats in stats.values():
        total_samples += key_stats.samples
        total_errors += key_stats.error_count
        weighted_time += key_stats.mean_time_ns * key_stats.samples
    total_attempts = total_samples + total_errors
    if total_attempts == 0:
        return 0.0, 0.0
    accuracy = round_confidence(total_samples / total_attempts)
    if total_samples > 0:
        speed = round_confidence(
            key_confidence(target_ms, weighted_time / total_samples),
        )
    else:
        speed = 0.0
    return speed, accuracy


def _aggregate_confidence(
    stats: Mapping[int, KeyStats],
    target_ms: float,
    min_attempts: int,
) -> float:
    total_weight = 0.0
    weighted_sum = 0.0
    for cp, key_stats in stats.items():
        attempts = key_attempts(key_stats)
        if attempts == 0:
            continue
        conf = confidence_of(cp, stats, target_ms, min_attempts=min_attempts)
        weighted_sum += conf * attempts
        total_weight += attempts
    if total_weight == 0:
        return 0.0
    return round_confidence(weighted_sum / total_weight)


def _windowed_session_replays(
    repo: SessionRepository,
    all_headers: list[SessionResult],
    window: int,
    fallback_target: float,
) -> Iterator[tuple[SessionResult, Mapping[int, KeyStats], float]]:
    """Replay each session in the trailing window against its own trailing
    confidence window, yielding the combined per-key stats as of that session."""
    ordered = all_headers[-window:]
    start_offset = len(all_headers) - len(ordered)
    for rel_i, header in enumerate(ordered):
        abs_i = start_offset + rel_i
        window_headers = all_headers[max(0, abs_i - window + 1) : abs_i + 1]
        sessions = [(h, repo.load_keystrokes(h.session_id)) for h in window_headers]
        combined = combine_sessions(sessions).keys
        if header.target_speed_cpm > 0:
            session_target = target_ms_per_char(header.target_speed_cpm)
        else:
            session_target = fallback_target
        yield header, combined, session_target


def _accumulate_windowed_trends(
    repo: SessionRepository,
    settings_repo: SettingsRepository,
    layout: str,
    current_target_speed_cpm: int,
    compute: Callable[[Mapping[int, KeyStats], float, int], tuple[float, float, float]],
) -> list[SessionMetrics]:
    """Shared windowed-replay accumulation for per-session trend lines.

    ``compute`` receives the combined per-key stats, the session's own target
    speed (ms/char), and the settings' min-confidence-attempts, and returns
    (raw speed confidence, accuracy, confidence) for that session — the raw
    speed is then normalized to the caller's current target goal.
    """
    settings = settings_repo.load()
    window = settings.confidence_session_window
    fallback_target = target_ms_per_char(settings.target_speed_cpm)
    min_attempts = settings.min_confidence_attempts

    all_headers = sorted(
        repo.iter_headers(layout),
        key=lambda h: h.started_at,
    )
    if not all_headers:
        return []

    metrics: list[SessionMetrics] = []
    for header, combined, session_target in _windowed_session_replays(
        repo,
        all_headers,
        window,
        fallback_target,
    ):
        raw_speed, accuracy, confidence = compute(combined, session_target, min_attempts)
        speed = round_confidence(
            _normalize_speed_to_current_goal(
                raw_speed,
                header.target_speed_cpm,
                current_target_speed_cpm,
            ),
        )
        metrics.append(SessionMetrics(speed=speed, accuracy=accuracy, confidence=confidence))

    return metrics


def _key_metric_trends(
    repo: SessionRepository,
    settings_repo: SettingsRepository,
    layout: str,
    codepoint: int,
    *,
    current_target_speed_cpm: int = 0,
) -> list[SessionMetrics]:
    def compute(
        combined: Mapping[int, KeyStats],
        session_target: float,
        min_attempts: int,
    ) -> tuple[float, float, float]:
        key_stats = combined.get(codepoint)
        if key_stats is None or (key_stats.samples == 0 and key_stats.error_count == 0):
            return 0.0, 0.0, 0.0
        raw_speed = round_confidence(
            key_confidence(session_target, key_stats.mean_time_ns),
        )
        accuracy = round_confidence(accuracy_of(key_stats))
        confidence = confidence_of(
            codepoint,
            combined,
            session_target,
            min_attempts=min_attempts,
        )
        return raw_speed, accuracy, confidence

    return _accumulate_windowed_trends(
        repo,
        settings_repo,
        layout,
        current_target_speed_cpm,
        compute,
    )


def _aggregate_metric_trends(
    repo: SessionRepository,
    settings_repo: SettingsRepository,
    layout: str,
    *,
    current_target_speed_cpm: int = 0,
) -> list[SessionMetrics]:
    def compute(
        combined: Mapping[int, KeyStats],
        session_target: float,
        min_attempts: int,
    ) -> tuple[float, float, float]:
        speed, accuracy = _aggregate_speed_accuracy(combined, session_target)
        confidence = _aggregate_confidence(combined, session_target, min_attempts)
        return speed, accuracy, confidence

    return _accumulate_windowed_trends(
        repo,
        settings_repo,
        layout,
        current_target_speed_cpm,
        compute,
    )


@dataclass(slots=True)
class GetKeyMetricTrends:
    """Per-session speed and accuracy trends for one key.

    Replays the confidence session window at each session end (same window as
    stored key_confidence snapshots) and returns raw speed confidence and
    accuracy matching the practice focus-note metrics.
    """

    repo: SessionRepository
    settings_repo: SettingsRepository

    def __call__(
        self,
        layout: str,
        codepoint: int,
        *,
        current_target_speed_cpm: int = 0,
    ) -> tuple[list[float], list[float]]:
        metrics = _key_metric_trends(
            self.repo,
            self.settings_repo,
            layout,
            codepoint,
            current_target_speed_cpm=current_target_speed_cpm,
        )
        speeds = [m.speed for m in metrics]
        accuracies = [m.accuracy for m in metrics]
        return speeds, accuracies


@dataclass(slots=True)
class GetAggregateMetricTrends:
    """Per-session layout-wide confidence, speed, and accuracy trends.

    Same replay window as ``GetKeyMetricTrends``, but aggregates across all keys
    with attempt-weighted mean confidence, speed, and overall accuracy.
    """

    repo: SessionRepository
    settings_repo: SettingsRepository

    def __call__(
        self,
        layout: str,
        *,
        current_target_speed_cpm: int = 0,
    ) -> tuple[list[float], list[float], list[float]]:
        metrics = _aggregate_metric_trends(
            self.repo,
            self.settings_repo,
            layout,
            current_target_speed_cpm=current_target_speed_cpm,
        )
        confidences = [m.confidence for m in metrics]
        speeds = [m.speed for m in metrics]
        accuracies = [m.accuracy for m in metrics]
        return confidences, speeds, accuracies
