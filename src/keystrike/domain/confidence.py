"""Pure confidence math for keybr-style progression.

Used by the M2 Stats heatmap and the M3 adaptive engine's key-unlock / focus-
selection logic (§6 of PLAN.md).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from .enums import FocusKind
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
# Defaults for Settings and generator call sites; tunable via settings.toml.
FOCUS_CHAR_BOOST = 3.0
FOCUS_WORD_BOOST = 3.0
FOCUS_BIGRAM_WORD_BOOST = 4.0
FOCUS_TRANSITION_BOOST = 4.0
FOCUS_WEAK_EXTRA_BOOST = 1.5


@dataclass(frozen=True, slots=True)
class FocusReason:
    """Why the adaptive engine is emphasizing today's lesson focus. Replaces
    the old ad-hoc strings/formatted-string focus reasons; `pair` is set only
    for the TRANSITION_* kinds. Presentation code pattern-matches on `kind`
    to render its own display text instead of parsing suffixes/substrings."""

    kind: FocusKind
    pair: Bigram | None = None


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


def _accuracy(stats: HasConfidenceFields) -> float:
    """Fraction of attempts that were correct. 0.0 for a stat with no correct
    attempts yet, including one that's been missed but never hit."""
    samples = stats.samples
    if samples <= 0 and stats.mean_time_ns > 0:
        samples = 1
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
    if mean_time_ns > 0:
        return 1
    return 0


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


def _confidence_from_stats(
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
    return _confidence_from_stats(stats.get(codepoint), target, min_attempts=min_attempts)


def _measured_transitions_meet_threshold(
    unlocked: Sequence[int],
    transitions: Mapping[Bigram, TransitionStats],
    target: float,
    *,
    threshold: float,
    min_attempts: int,
) -> bool:
    """True when every measured bigram among unlocked keys meets threshold."""
    for prev in unlocked:
        for nxt in unlocked:
            if is_same_key_transition(prev, nxt):
                continue
            if Bigram(prev, nxt) not in transitions:
                continue
            if (
                transition_confidence_of(
                    prev,
                    nxt,
                    transitions,
                    target,
                    min_attempts=min_attempts,
                )
                < threshold
            ):
                return False
    return True


def compute_unlocked(
    learn_order: Sequence[int],
    alphabet_size: int,
    stats: Mapping[int, KeyStats],
    target: float,
    *,
    threshold: float = 1.0,
    min_attempts: int = MIN_CONFIDENCE_ATTEMPTS,
    transitions: Mapping[Bigram, TransitionStats] | None = None,
    min_transition_attempts: int = MIN_TRANSITION_CONFIDENCE_ATTEMPTS,
) -> tuple[int, ...]:
    """The first `alphabet_size` keys are always unlocked; each further key in
    `learn_order` unlocks only once every currently-unlocked key and every
    measured bigram among them meets `threshold`."""
    forced_count = min(alphabet_size, len(learn_order))
    unlocked = list(learn_order[:forced_count])
    for codepoint in learn_order[forced_count:]:
        if not all(
            confidence_of(k, stats, target, min_attempts=min_attempts) >= threshold
            for k in unlocked
        ):
            break
        if transitions is not None and not _measured_transitions_meet_threshold(
            unlocked,
            transitions,
            target,
            threshold=threshold,
            min_attempts=min_transition_attempts,
        ):
            break
        unlocked.append(codepoint)
    return tuple(unlocked)


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
    return _confidence_from_stats(
        stats.get(Bigram(prev_cp, next_cp)),
        target,
        min_attempts=min_attempts,
    )


def transition_practice_weight(
    confidence: float,
    *,
    max_bias: float = 3.0,
    urgency: float = 0.0,
    review_bias: float = 1.0,
) -> float:
    """Sampling weight for a prev→next pair — mirrors `practice_weight`."""
    return practice_weight(
        confidence,
        max_bias=max_bias,
        urgency=urgency,
        review_bias=review_bias,
    )


def practice_weight(
    confidence: float,
    *,
    max_bias: float = 3.0,
    urgency: float = 0.0,
    review_bias: float = 1.0,
) -> float:
    """Sampling weight for practice-text generation: a weak key (confidence 0)
    gets `1 + max_bias` the weight of a mastered key (confidence >= 1.0), so
    generated text is deliberately concentrated on weak keys rather than
    treating every unlocked key as equally likely to appear (see "Deliberate
    practice targeting weak points" in docs/research/typing-pedagogy.md).
    Capped at confidence 1.0 so an already-fast key doesn't get pushed below
    baseline weight just for being unusually fast.

    `urgency` (from `review_urgency`) multiplies weight so stale-but-mastered
    keys still appear in generated text."""
    base = 1.0 + max_bias * (1.0 - min(confidence, 1.0))
    return base * (1.0 + review_bias * urgency)


def _focus_score_from_entry(
    stats: HasConfidenceFields | None,
    target: float,
    now: float,
    *,
    review_penalty: float,
    min_attempts: int,
) -> float:
    """Shared body for `_focus_score`/`_transition_focus_score`: confidence,
    discounted further the longer it's been since last practiced, so a stale
    mastered key/pair can still outrank a merely-weak recent one."""
    urgency = review_urgency(stats.last_seen if stats else 0.0, now)
    confidence = _confidence_from_stats(stats, target, min_attempts=min_attempts)
    return confidence * (1.0 - review_penalty * urgency)


def _focus_score(
    codepoint: int,
    stats: Mapping[int, KeyStats],
    target: float,
    now: float,
    *,
    review_penalty: float,
    min_attempts: int = MIN_CONFIDENCE_ATTEMPTS,
) -> float:
    return _focus_score_from_entry(
        stats.get(codepoint),
        target,
        now,
        review_penalty=review_penalty,
        min_attempts=min_attempts,
    )


def has_weak_unlocked_key(
    unlocked: Sequence[int],
    stats: Mapping[int, KeyStats],
    target: float,
    *,
    threshold: float = 1.0,
    min_attempts: int = MIN_CONFIDENCE_ATTEMPTS,
) -> bool:
    """True when any unlocked key is below mastery threshold."""
    return any(
        confidence_of(cp, stats, target, min_attempts=min_attempts) < threshold for cp in unlocked
    )


def select_focus(
    unlocked: Sequence[int],
    stats: Mapping[int, KeyStats],
    target: float,
    now: float,
    *,
    review_penalty: float = 0.5,
    min_attempts: int = MIN_CONFIDENCE_ATTEMPTS,
) -> int:
    """The unlocked key a lesson should emphasize — weakest by confidence, but
    stale keys are treated as weaker so high-confidence keys due for review
    still surface (SlimStampen-style spacing; see typing-pedagogy.md)."""
    return min(
        unlocked,
        key=lambda cp: _focus_score(
            cp,
            stats,
            target,
            now,
            review_penalty=review_penalty,
            min_attempts=min_attempts,
        ),
    )


def _transition_focus_score(
    prev_cp: int,
    next_cp: int,
    stats: Mapping[Bigram, TransitionStats],
    target: float,
    now: float,
    *,
    review_penalty: float,
    min_attempts: int = MIN_TRANSITION_CONFIDENCE_ATTEMPTS,
) -> float:
    return _focus_score_from_entry(
        stats.get(Bigram(prev_cp, next_cp)),
        target,
        now,
        review_penalty=review_penalty,
        min_attempts=min_attempts,
    )


def select_focus_transition(
    unlocked: Sequence[int],
    transitions: Mapping[Bigram, TransitionStats],
    target: float,
    now: float,
    *,
    review_penalty: float = 0.5,
    min_attempts: int = MIN_TRANSITION_CONFIDENCE_ATTEMPTS,
) -> Bigram | None:
    """Weakest unlocked bigram by transition confidence; None when no transition data."""
    if not transitions:
        return None
    pairs = [
        Bigram(prev, nxt)
        for prev in unlocked
        for nxt in unlocked
        if not is_same_key_transition(prev, nxt) and Bigram(prev, nxt) in transitions
    ]
    if not pairs:
        return None
    return min(
        pairs,
        key=lambda p: _transition_focus_score(
            p[0],
            p[1],
            transitions,
            target,
            now,
            review_penalty=review_penalty,
            min_attempts=min_attempts,
        ),
    )


def focus_key_from_transition(_prev_cp: int, next_cp: int) -> int:
    """Endpoint key to mark as lesson focus for a transition-driven bigram."""
    return next_cp
