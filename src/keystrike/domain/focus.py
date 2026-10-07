"""Focus/practice-weight selection: which key or transition today's lesson
should emphasize, and how much sampling weight weak/stale keys get in
generated practice text (§6 of PLAN.md)."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from .confidence import (
    CONFIDENCE_GOOD,
    MIN_CONFIDENCE_ATTEMPTS,
    MIN_TRANSITION_CONFIDENCE_ATTEMPTS,
    HasConfidenceFields,
    attempts_of,
    clears_threshold,
    confidence_from_stats,
    review_urgency,
    stall_attempts_cap,
)
from .enums import FocusKind
from .models import (
    FOCUS_BIGRAM_WORD_BOOST,
    FOCUS_WORD_BOOST,
    Bigram,
    KeyStats,
    TransitionStats,
)
from .newest_key import unlocked_cross_key_pairs

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


def _cleared(stats: HasConfidenceFields | None, target: float, min_attempts: int) -> bool:
    return clears_threshold(stats, target, threshold=CONFIDENCE_GOOD, min_attempts=min_attempts)


def _stalled(stats: HasConfidenceFields | None, min_attempts: int) -> bool:
    """Enough presses that holding focus longer is not helping (plateau):
    the same cap the transition gate uses to stop waiting on a pair."""
    return stats is not None and attempts_of(stats) >= stall_attempts_cap(min_attempts)


def _pick[T](
    candidates: Sequence[T],
    last: T | None,
    stats_of: Callable[[T], HasConfidenceFields | None],
    min_attempts: int,
    rank: Callable[[T], float],
) -> T:
    """The last lesson's focus while it is still a candidate and not stalled,
    else the lowest-ranked candidate."""
    if last is not None and last in candidates and not _stalled(stats_of(last), min_attempts):
        return last
    return min(candidates, key=rank)


def select_lesson_focus(
    unlocked: Sequence[int],
    key_stats: Mapping[int, KeyStats],
    transitions: Mapping[Bigram, TransitionStats],
    target: float,
    now: float,
    *,
    pair_frequency: Callable[[Bigram], float],
    gate: Sequence[Bigram] = (),
    last_key: int | None = None,
    last_pair: Bigram | None = None,
    min_attempts: int = MIN_CONFIDENCE_ATTEMPTS,
    min_transition_attempts: int = MIN_TRANSITION_CONFIDENCE_ATTEMPTS,
) -> tuple[int, Bigram | None]:
    """Today's focus as (key, pair); pair is None for key focus, else the key
    is the pair's second letter. The first rule with candidates wins, and each
    rule keeps the last lesson's focus while it is still in that rule's list
    and not stalled (see docs/wiki/Focus-States.md):

    1. Keys not cleared (skill and attempt floor) -- weakest key.
    2. The newest key's `gate` pairs that block the next unlock -- weakest pair.
    3. Pairs not cleared that occur in the language -- highest
       (1 - confidence) x `pair_frequency`.
    4. Cleared keys and pairs due for review -- most overdue.
    5. Otherwise the weakest key.
    """

    def key_conf(cp: int) -> float:
        return confidence_from_stats(key_stats.get(cp), target, min_attempts=min_attempts)

    def pair_conf(pair: Bigram) -> float:
        return confidence_from_stats(
            transitions.get(pair), target, min_attempts=min_transition_attempts
        )

    weak_keys = [cp for cp in unlocked if not _cleared(key_stats.get(cp), target, min_attempts)]
    if weak_keys:
        return _pick(weak_keys, last_key, key_stats.get, min_attempts, key_conf), None

    if gate:
        pair = _pick(gate, last_pair, transitions.get, min_transition_attempts, pair_conf)
        return pair.next_cp, pair

    weak_pairs = [
        pair
        for pair in unlocked_cross_key_pairs(unlocked)
        if pair_frequency(pair) > 0
        and not _cleared(transitions.get(pair), target, min_transition_attempts)
    ]
    if weak_pairs:
        pair = _pick(
            weak_pairs,
            last_pair,
            transitions.get,
            min_transition_attempts,
            lambda p: -(1.0 - pair_conf(p)) * pair_frequency(p),
        )
        return pair.next_cp, pair

    def urgency(stats: HasConfidenceFields | None) -> float:
        return review_urgency(stats.last_seen if stats else 0.0, now)

    due = [(urgency(key_stats.get(cp)), cp, None) for cp in unlocked] + [
        (urgency(transitions.get(pair)), pair.next_cp, pair)
        for pair in unlocked_cross_key_pairs(unlocked)
    ]
    most_due, key, pair = max(due, key=lambda entry: entry[0])
    if most_due > 0:
        return key, pair

    return min(unlocked, key=key_conf), None


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
