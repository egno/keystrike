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
    confidence_of,
    is_same_key_transition,
    review_urgency,
)
from .enums import FocusKind
from .models import Bigram, KeyStats, TransitionStats

# Defaults for Settings and generator call sites; tunable via settings.toml.
FOCUS_CHAR_BOOST = 3.0
FOCUS_WORD_BOOST = 3.0
FOCUS_BIGRAM_WORD_BOOST = 4.0
FOCUS_TRANSITION_BOOST = 4.0
FOCUS_WEAK_EXTRA_BOOST = 1.5

_TRANSITION_KINDS = (FocusKind.TRANSITION_WEAK, FocusKind.TRANSITION_REVIEW)


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
