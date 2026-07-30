"""Pure confidence/accuracy scoring and spaced-review urgency for keybr-style
progression.

Used by the M2 Stats heatmap and the M3 adaptive engine's key-unlock / focus-
selection logic (§6 of PLAN.md). Key-unlock policy lives in `domain.unlock`;
focus/practice-weight selection lives in `domain.focus` — both build on the
scoring primitives here.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from .models import Bigram, KeyStats, TransitionStats

_SECONDS_PER_DAY = 86_400.0
_REVIEW_URGENCY_FULL_DAYS = 3.0
# Confidence, unlocks, focus, and heatmap use aggregates from this many sessions.
CONFIDENCE_SESSION_WINDOW = 10
# Exponential decay per session step when merging windowed stats (most recent = 1.0).
# ponytail: fixed constant; upgrade to settings if users want tunable recency bias.
SESSION_RECENCY_DECAY = 0.7
# Raw min(speed, accuracy) confidence ramps linearly until this many attempts per key.
MIN_CONFIDENCE_ATTEMPTS = 10
# Bigrams are sparser — lower floor so transition focus reflects measured weakness.
MIN_TRANSITION_CONFIDENCE_ATTEMPTS = 4
# Confidence scores are rounded before thresholds, focus, heatmap, and UI.
CONFIDENCE_DECIMALS = 2


def round_confidence(value: float) -> float:
    """Round confidence for comparisons and display so they stay aligned."""
    return round(value, CONFIDENCE_DECIMALS)


def target_ms_per_char(target_speed_cpm: int) -> float:
    return 60_000.0 / target_speed_cpm


def key_confidence(target_ms_per_char: float, mean_time_ns: float) -> float:
    """Speed confidence = target / actual. > 1.0 is above target, < 1.0 is below."""
    if mean_time_ns <= 0:
        return 0.0
    return target_ms_per_char / (mean_time_ns / 1e6)


class HasConfidenceFields(Protocol):
    """Structural shape shared by `KeyStats` and `TransitionStats`: everything
    the confidence/accuracy/attempts math needs, regardless of whether the
    stat is keyed by a single codepoint or a `Bigram`. Lets the functions
    below have one body each instead of a key-variant and a transition-variant.

    Declared as read-only properties (not plain attributes) so the frozen
    `KeyStats`/`TransitionStats` dataclasses structurally satisfy it — a
    protocol with mutable attribute requirements would reject them."""

    @property
    def samples(self) -> int: ...
    @property
    def error_count(self) -> int: ...
    @property
    def attempt_count(self) -> int: ...
    @property
    def mean_time_ns(self) -> float: ...
    @property
    def last_seen(self) -> float: ...


def _inferred_attempt(mean_time_ns: float) -> int:
    """One inferred attempt when a stat has measured timing but its counts were
    zeroed (stale cache / old merge) — the shared fallback rule that keeps
    `_accuracy` and `_effective_attempt_count` aligned."""
    return 1 if mean_time_ns > 0 else 0


def _accuracy(stats: HasConfidenceFields) -> float:
    """Fraction of attempts that were correct. 0.0 for a stat with no correct
    attempts yet, including one that's been missed but never hit."""
    samples = stats.samples
    if samples <= 0:
        samples = _inferred_attempt(stats.mean_time_ns)
    total = samples + stats.error_count
    return samples / total if total > 0 else 0.0


def accuracy_of(key_stats: KeyStats) -> float:
    return _accuracy(key_stats)


def _effective_attempt_count(
    samples: int,
    error_count: int,
    attempt_count: int,
    *,
    mean_time_ns: float = 0.0,
) -> int:
    """Use samples+errors when attempt_count was zeroed (stale cache / old merge).

    When mean_time_ns is measured but all counts were zeroed, infer at least one
    attempt so confidence stays aligned with `_accuracy` (same fallback rule).
    """
    if attempt_count > 0:
        return attempt_count
    inferred = samples + error_count
    if inferred > 0:
        return inferred
    return _inferred_attempt(mean_time_ns)


def _attempts(stats: HasConfidenceFields) -> int:
    return _effective_attempt_count(
        stats.samples,
        stats.error_count,
        stats.attempt_count,
        mean_time_ns=stats.mean_time_ns,
    )


def key_attempts(key_stats: KeyStats) -> int:
    return _attempts(key_stats)


def transition_attempts(transition_stats: TransitionStats) -> int:
    return _attempts(transition_stats)


def is_same_key_transition(prev_cp: int, next_cp: int) -> bool:
    """Same physical key twice (e.g. ee, ss) — excluded from transition analysis."""
    return prev_cp == next_cp


def confidence_sample_factor(
    attempts: int,
    *,
    minimum: int = MIN_CONFIDENCE_ATTEMPTS,
) -> float:
    """Ramp toward full confidence as attempts accumulate (ponytail: linear;
    upgrade to Wilson interval or similar if sparse keys still feel jumpy)."""
    if minimum <= 0:
        return 1.0
    if attempts <= 0:
        return 0.0
    return min(1.0, attempts / minimum)


def confidence_from_stats(
    stats: HasConfidenceFields | None,
    target: float,
    *,
    min_attempts: int,
) -> float:
    """Shared body for `confidence_of`/`transition_confidence_of`: min(speed,
    accuracy) so fast-but-sloppy or slow-but-accurate cannot read as mastered,
    scaled down until `min_attempts` so a lucky first session can't read as
    mastered (see docs/research/typing-pedagogy.md). 0.0 when never practiced.
    """
    if stats is None:
        return 0.0
    raw = min(key_confidence(target, stats.mean_time_ns), _accuracy(stats))
    return round_confidence(raw * confidence_sample_factor(_attempts(stats), minimum=min_attempts))


def confidence_of(
    codepoint: int,
    stats: Mapping[int, KeyStats],
    target: float,
    *,
    min_attempts: int = MIN_CONFIDENCE_ATTEMPTS,
) -> float:
    """Live confidence for one key from aggregated stats (typically the last
    `CONFIDENCE_SESSION_WINDOW` sessions, recency-weighted), recomputed from
    the current target. 0.0 for a never-practiced key."""
    return confidence_from_stats(stats.get(codepoint), target, min_attempts=min_attempts)


def review_urgency(last_seen: float, now: float) -> float:
    """How urgently a key needs re-testing before forgetting (0.0-1.0).

    ponytail: fixed day-scale ramp, not per-key ACT-R decay; upgrade to
    SlimStampen-style individual half-life once we have enough per-key history.
    """
    if last_seen <= 0 or now <= last_seen:
        return 0.0
    elapsed_days = (now - last_seen) / _SECONDS_PER_DAY
    if elapsed_days < 1.0:
        return 0.0
    if elapsed_days >= _REVIEW_URGENCY_FULL_DAYS:
        return 1.0
    return (elapsed_days - 1.0) / 2.0


def transition_accuracy_of(transition_stats: TransitionStats) -> float:
    return _accuracy(transition_stats)


def transition_confidence(target_ms_per_char: float, mean_time_ns: float) -> float:
    """Speed confidence for a transition — identical math to `key_confidence`,
    kept as a separate name so call sites read as transition- vs key-specific."""
    return key_confidence(target_ms_per_char, mean_time_ns)


def transition_confidence_of(
    prev_cp: int,
    next_cp: int,
    stats: Mapping[Bigram, TransitionStats],
    target: float,
    *,
    min_attempts: int = MIN_TRANSITION_CONFIDENCE_ATTEMPTS,
) -> float:
    """Live confidence for one bigram transition. 0.0 when never practiced."""
    return confidence_from_stats(
        stats.get(Bigram(prev_cp, next_cp)),
        target,
        min_attempts=min_attempts,
    )
