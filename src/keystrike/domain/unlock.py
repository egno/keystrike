"""Key-unlock policy: which keys in `learn_order` are currently unlocked,
gated on measured per-key and per-transition confidence (§6 of PLAN.md)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from .confidence import (
    MIN_CONFIDENCE_ATTEMPTS,
    MIN_TRANSITION_CONFIDENCE_ATTEMPTS,
    confidence_of,
    is_same_key_transition,
    transition_confidence_of,
)
from .models import Bigram, KeyStats, TransitionStats


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
