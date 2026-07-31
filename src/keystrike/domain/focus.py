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
    confidence_from_stats,
    is_same_key_transition,
    review_urgency,
    skill_of,
)
from .enums import FocusKind
from .models import (
    FOCUS_BIGRAM_WORD_BOOST,
    FOCUS_WORD_BOOST,
    Bigram,
    KeyStats,
    TransitionStats,
)

# Re-exported for domain.generator, which imports these boost defaults from
# this module rather than `domain.models` directly.
__all__ = ["FOCUS_BIGRAM_WORD_BOOST", "FOCUS_WORD_BOOST"]

_UNMEASURED_PAIR_FALLBACK_UNLOCKED_SIZE = 2

_TRANSITION_KINDS = (
    FocusKind.TRANSITION_WEAK,
    FocusKind.TRANSITION_CALIBRATING,
    FocusKind.TRANSITION_REVIEW,
)


@dataclass(frozen=True, slots=True)
class FocusReason:
    """Why the adaptive engine is emphasizing today's lesson focus. Replaces
    the old ad-hoc strings/formatted-string focus reasons; `pair` is set only
    for the TRANSITION_* kinds. Presentation code pattern-matches on `kind`
    to render its own display text instead of parsing suffixes/substrings."""

    kind: FocusKind
    pair: Bigram | None = None

    def __post_init__(self) -> None:
        is_transition_kind = self.kind in _TRANSITION_KINDS
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
) -> bool:
    """True when any unlocked key with measured stats is below performance skill.

    Never-practiced keys (absent from stats) do not block — e.g. a key just
    auto-unlocked before its first press. Keys in stats with skill 0 still block."""
    return any(cp in stats and skill_of(cp, stats, target) < threshold for cp in unlocked)


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


def _unlocked_cross_key_pairs(unlocked: Sequence[int]) -> list[Bigram]:
    return [
        Bigram(prev, nxt)
        for prev in unlocked
        for nxt in unlocked
        if not is_same_key_transition(prev, nxt)
    ]


def select_focus_transition(
    unlocked: Sequence[int],
    transitions: Mapping[Bigram, TransitionStats],
    target: float,
    now: float,
    *,
    key_stats: Mapping[int, KeyStats] | None = None,
    review_penalty: float = 0.5,
    min_attempts: int = MIN_TRANSITION_CONFIDENCE_ATTEMPTS,
) -> Bigram | None:
    """Weakest unlocked bigram by transition confidence.

    Measured pairs are preferred. When none exist yet but every unlocked key
    has been practiced (typical two-key drills before cross-key stats land),
    fall back to the weakest-scoring unmeasured cross-key pair."""
    pairs = [pair for pair in _unlocked_cross_key_pairs(unlocked) if pair in transitions]
    if pairs:
        return min(
            pairs,
            key=lambda p: _transition_focus_score(
                p.prev_cp,
                p.next_cp,
                transitions,
                target,
                now,
                review_penalty=review_penalty,
                min_attempts=min_attempts,
            ),
        )
    if key_stats is None or not all(cp in key_stats for cp in unlocked):
        return None
    # ponytail: two-key drills only; larger alphabets should wait for measured pairs
    if len(unlocked) != _UNMEASURED_PAIR_FALLBACK_UNLOCKED_SIZE:
        return None
    candidates = _unlocked_cross_key_pairs(unlocked)
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda p: _transition_focus_score(
            p.prev_cp,
            p.next_cp,
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
