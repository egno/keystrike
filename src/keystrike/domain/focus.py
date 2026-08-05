"""Focus/practice-weight selection: which key or transition today's lesson
should emphasize, and how much sampling weight weak/stale keys get in
generated practice text (§6 of PLAN.md)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from .confidence import (
    MIN_CONFIDENCE_ATTEMPTS,
    MIN_TRANSITION_CONFIDENCE_ATTEMPTS,
    HasConfidenceFields,
    attempts_of,
    clears_threshold,
    confidence_from_stats,
    review_urgency,
    skill_from_stats,
)
from .enums import FocusKind
from .models import (
    FOCUS_BIGRAM_WORD_BOOST,
    FOCUS_WORD_BOOST,
    Bigram,
    KeyStats,
    TransitionStats,
)
from .newest_key import newest_practiced_key_pairs, unlocked_cross_key_pairs

# Re-exported for domain.generator, which imports these boost defaults from
# this module rather than `domain.models` directly.
__all__ = ["FOCUS_BIGRAM_WORD_BOOST", "FOCUS_WORD_BOOST"]


@dataclass(frozen=True, slots=True)
class FocusReason:
    """Why the adaptive engine is emphasizing today's lesson focus. Replaces
    the old ad-hoc strings/formatted-string focus reasons; `pair` is set only
    for the TRANSITION_* kinds. Presentation code pattern-matches on `kind`
    to render its own display text instead of parsing suffixes/substrings."""

    kind: FocusKind
    pair: Bigram | None = None

    @property
    def is_transition(self) -> bool:
        return self.kind in (
            FocusKind.TRANSITION_WEAK,
            FocusKind.TRANSITION_CALIBRATING,
            FocusKind.TRANSITION_REVIEW,
        )

    def __post_init__(self) -> None:
        is_transition_kind = self.is_transition
        if is_transition_kind and self.pair is None:
            raise ValueError(f"{self.kind} requires a pair")
        if not is_transition_kind and self.pair is not None:
            raise ValueError(f"{self.kind} must not have a pair")


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
    confidence = confidence_from_stats(stats, target, min_attempts=min_attempts)
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


def blocks_transition_focus(
    unlocked: Sequence[int],
    stats: Mapping[int, KeyStats],
    target: float,
    *,
    threshold: float = 1.0,
    min_attempts: int = MIN_CONFIDENCE_ATTEMPTS,
) -> bool:
    """True when any unlocked key lacks required performance or evidence."""
    return any(
        not clears_threshold(stats.get(cp), target, threshold=threshold, min_attempts=min_attempts)
        for cp in unlocked
    )


def select_focus(
    unlocked: Sequence[int],
    stats: Mapping[int, KeyStats],
    target: float,
    now: float,
    *,
    review_penalty: float = 0.5,
    threshold: float = 1.0,
    min_attempts: int = MIN_CONFIDENCE_ATTEMPTS,
) -> int:
    """The unlocked key a lesson should emphasize.

    Any key that hasn't yet cleared both the skill threshold and the attempt
    floor (`clears_threshold`) wins over every key that has — so focus stays
    on an in-progress key across lesson builds instead of a mastered-but-
    stale key's review-urgency discount stealing it away mid-calibration.
    Only once every unlocked key has cleared does review-urgency-based
    staleness compete for focus among the whole set (SlimStampen-style
    spacing; see typing-pedagogy.md)."""
    candidates = [
        cp
        for cp in unlocked
        if not clears_threshold(
            stats.get(cp), target, threshold=threshold, min_attempts=min_attempts
        )
    ]
    pool = candidates or unlocked
    return min(
        pool,
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


def newest_key_unmeasured_pairs(
    unlocked: Sequence[int],
    transitions: Mapping[Bigram, TransitionStats],
    key_stats: Mapping[int, KeyStats] | None,
) -> list[Bigram]:
    """Cross-key pairs between the most-recently-*practiced* unlocked key and
    its other already-practiced unlocked peers, when none of those pairs
    have measured transition data yet.

    Built on `domain.newest_key.newest_practiced_key_pairs`, the single
    source of truth shared with `domain.unlock.newest_key_clears_transition_gate`.
    Returns empty once the newest key has *any* measured transition
    (ordinary weakest-pair scoring takes over from there for focus
    selection), when no unlocked key has been practiced yet, or when it has
    no other practiced key to pair with."""
    unmeasured, measured = newest_practiced_key_pairs(unlocked, transitions, key_stats)
    return [] if measured else unmeasured


def select_focus_transition(
    unlocked: Sequence[int],
    transitions: Mapping[Bigram, TransitionStats],
    target: float,
    now: float,
    *,
    key_stats: Mapping[int, KeyStats] | None = None,
    gating_candidates: Sequence[Bigram] | None = None,
    review_penalty: float = 0.5,
    threshold: float = 1.0,
    min_attempts: int = MIN_TRANSITION_CONFIDENCE_ATTEMPTS,
) -> Bigram | None:
    """Weakest unlocked bigram by transition confidence.

    Measured pairs are preferred. But when the newest practiced key has no
    measured transitions of its own yet (`newest_key_unmeasured_pairs`), fall
    back to its weakest-scoring unmeasured pair — so a freshly-opened letter
    gets bigram focus right away instead of waiting for its pairs to appear
    by chance.

    Among measured pairs (outside `gating_candidates` mode), a pair that
    hasn't cleared both the skill threshold and attempt floor
    (`clears_threshold`) always wins over an already-cleared, merely-stale
    pair — the same stickiness `select_focus` applies to keys, so an
    in-progress bigram isn't preempted by review urgency before it's done
    calibrating. Once every measured pair has cleared, review-urgency-based
    staleness competes for focus among all of them, same as before."""

    def _score(pair: Bigram) -> float:
        return _transition_focus_score(
            pair.prev_cp,
            pair.next_cp,
            transitions,
            target,
            now,
            review_penalty=review_penalty,
            min_attempts=min_attempts,
        )

    measured = [pair for pair in unlocked_cross_key_pairs(unlocked) if pair in transitions]
    if gating_candidates is not None:
        gating_set = frozenset(gating_candidates)
        regressions = [
            pair
            for pair in measured
            if pair not in gating_set
            and attempts_of(transitions[pair]) >= min_attempts
            and skill_from_stats(transitions[pair], target) < 1.0
        ]
        if regressions:
            return min(regressions, key=_score)
        return min(gating_candidates, key=_score) if gating_candidates else None

    candidates = newest_key_unmeasured_pairs(unlocked, transitions, key_stats)
    if candidates:
        return min(candidates, key=_score)
    if not measured:
        return None
    not_cleared = [
        pair
        for pair in measured
        if not clears_threshold(
            transitions.get(pair), target, threshold=threshold, min_attempts=min_attempts
        )
    ]
    return min(not_cleared or measured, key=_score)


def focus_key_from_transition(_prev_cp: int, next_cp: int) -> int:
    """Endpoint key to mark as lesson focus for a transition-driven bigram."""
    return next_cp


def remedial_focus(
    lesson_alphabet: Sequence[int],
    unlocked: Sequence[int],
    stats: Mapping[int, KeyStats],
    transitions: Mapping[Bigram, TransitionStats],
    target: float,
    *,
    now: float,
    threshold: float = 1.0,
    min_attempts: int = MIN_CONFIDENCE_ATTEMPTS,
    min_transition_attempts: int = MIN_TRANSITION_CONFIDENCE_ATTEMPTS,
) -> tuple[int, Bigram | None] | None:
    """Weakest key or bigram confined to one already-finished lesson's own
    alphabet — pulls focus back onto that lesson's own weak point when its
    WPM fell short of target, instead of ordinary weakest-across-window
    selection (or the newest-key transition gate) drifting focus elsewhere.

    None once every key in the pool has cleared and no bigram among them is
    left wanting either — callers should fall back to ordinary focus
    selection at that point (the lesson's weak point is resolved)."""
    pool = [cp for cp in unlocked if cp in frozenset(lesson_alphabet)]
    if not pool:
        return None
    if blocks_transition_focus(pool, stats, target, threshold=threshold, min_attempts=min_attempts):
        focus = select_focus(
            pool, stats, target, now, threshold=threshold, min_attempts=min_attempts
        )
        return focus, None
    bigram = select_focus_transition(
        pool,
        transitions,
        target,
        now,
        key_stats=stats,
        threshold=threshold,
        min_attempts=min_transition_attempts,
    )
    if bigram is None:
        return None
    return focus_key_from_transition(*bigram), bigram


def coverage_deficit_factor(
    attempts: int,
    *,
    min_attempts: int = MIN_CONFIDENCE_ATTEMPTS,
    max_boost: float = 2.0,
) -> float:
    """Session-scale boost when in-window attempts are below ``min_attempts``.

    Separate from performance weakness (``practice_weight``) and day-scale
    ``review_urgency`` — targets keys that need more window samples to unlock
    or calibrate, peaking at zero attempts."""
    if min_attempts <= 0 or attempts >= min_attempts:
        return 1.0
    deficit = 1.0 - attempts / min_attempts
    return 1.0 + max_boost * deficit


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
