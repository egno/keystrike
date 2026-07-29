"""Use cases for rebuilding and reading per-layout key-stats aggregates."""

from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass

from keystrike.domain.aggregate import combine_sessions, per_key_deltas
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


def _normalize_speed_to_current_goal(
    speed: float,
    stored_target_cpm: int,
    current_target_cpm: int,
) -> float:
    if stored_target_cpm <= 0 or current_target_cpm <= 0:
        return speed
    return speed * (
        target_ms_per_char(current_target_cpm)
        / target_ms_per_char(stored_target_cpm)
    )


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


def _metric_trends(
    repo: SessionRepository,
    settings_repo: SettingsRepository,
    layout: str,
    codepoint: int | None,
    *,
    current_target_speed_cpm: int = 0,
) -> tuple[list[float], list[float], list[float]]:
    settings = settings_repo.load()
    window = settings.confidence_session_window
    fallback_target = target_ms_per_char(settings.target_speed_cpm)
    min_attempts = settings.min_confidence_attempts

    all_headers = sorted(
        repo.iter_headers(layout),
        key=lambda h: h.started_at,
    )
    if not all_headers:
        return [], [], []

    ordered = all_headers[-window:]
    start_offset = len(all_headers) - len(ordered)

    speeds: list[float] = []
    accuracies: list[float] = []
    confidences: list[float] = []
    for rel_i, header in enumerate(ordered):
        abs_i = start_offset + rel_i
        window_headers = all_headers[max(0, abs_i - window + 1):abs_i + 1]
        sessions = [
            (h, repo.load_keystrokes(h.session_id)) for h in window_headers
        ]
        combined = combine_sessions(sessions).keys

        if header.target_speed_cpm > 0:
            session_target = target_ms_per_char(header.target_speed_cpm)
        else:
            session_target = fallback_target

        if codepoint is not None:
            key_stats = combined.get(codepoint)
            if key_stats is None or (
                key_stats.samples == 0 and key_stats.error_count == 0
            ):
                speeds.append(0.0)
                accuracies.append(0.0)
                confidences.append(0.0)
                continue
            raw_speed = round_confidence(
                key_confidence(session_target, key_stats.mean_time_ns),
            )
            speed = round_confidence(
                _normalize_speed_to_current_goal(
                    raw_speed,
                    header.target_speed_cpm,
                    current_target_speed_cpm,
                ),
            )
            accuracy = round_confidence(accuracy_of(key_stats))
            confidence = confidence_of(
                codepoint, combined, session_target, min_attempts=min_attempts,
            )
        else:
            speed, accuracy = _aggregate_speed_accuracy(combined, session_target)
            speed = round_confidence(
                _normalize_speed_to_current_goal(
                    speed,
                    header.target_speed_cpm,
                    current_target_speed_cpm,
                ),
            )
            confidence = _aggregate_confidence(
                combined, session_target, min_attempts,
            )

        speeds.append(speed)
        accuracies.append(accuracy)
        confidences.append(confidence)

    return speeds, accuracies, confidences


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
        speeds, accuracies, _ = _metric_trends(
            self.repo,
            self.settings_repo,
            layout,
            codepoint,
            current_target_speed_cpm=current_target_speed_cpm,
        )
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
        speeds, accuracies, confidences = _metric_trends(
            self.repo,
            self.settings_repo,
            layout,
            None,
            current_target_speed_cpm=current_target_speed_cpm,
        )
        return confidences, speeds, accuracies
