"""Key-unlock policy: which keys in `learn_order` are currently unlocked,
gated on per-key skill and attempt floor, plus (optionally) the newest key's
single weakest bigram (§6 of PLAN.md)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from .confidence import (
    MIN_CONFIDENCE_ATTEMPTS,
    MIN_TRANSITION_CONFIDENCE_ATTEMPTS,
    attempts_of,
    clears_threshold,
    transition_confidence_of,
)
from .models import GATING_BIGRAM_LIMIT, Bigram, KeyStats, TransitionStats
from .newest_key import newest_key_gating_cohort

# ponytail: fixed multiplier; upgrade to a Settings field if a stuck gating
# bigram turns out to need per-user tuning.
TRANSITION_STALL_ATTEMPTS_MULTIPLIER = 3


def default_transition_stall_attempts_cap(min_attempts: int) -> int:
    """Default `transition_stall_attempts_cap` for `compute_unlocked`: give a
    stuck gating bigram this many times the normal calibration floor before
    releasing it anyway. Single source of truth so callers that need the
    gate (`build_lesson`, `session_use_cases`) can't compute this
    differently and drift apart."""
    return min_attempts * TRANSITION_STALL_ATTEMPTS_MULTIPLIER


def newest_key_clears_transition_gate(
    unlocked: Sequence[int],
    transitions: Mapping[Bigram, TransitionStats],
    target: float,
    key_stats: Mapping[int, KeyStats] | None = None,
    *,
    threshold: float = 1.0,
    min_attempts: int = MIN_TRANSITION_CONFIDENCE_ATTEMPTS,
    stall_attempts_cap: int | None = None,
    cohort_limit: int = GATING_BIGRAM_LIMIT,
) -> bool:
    """Whether every member of the newest key's bounded cohort is ready."""
    ready, total = newest_key_transition_gate_progress(
        unlocked,
        transitions,
        target,
        key_stats,
        threshold=threshold,
        min_attempts=min_attempts,
        stall_attempts_cap=stall_attempts_cap,
        cohort_limit=cohort_limit,
    )
    return ready == total


def gating_bigram_is_ready(
    pair: Bigram,
    transitions: Mapping[Bigram, TransitionStats],
    target: float,
    *,
    threshold: float = 1.0,
    min_attempts: int = MIN_TRANSITION_CONFIDENCE_ATTEMPTS,
    stall_attempts_cap: int | None = None,
) -> bool:
    stats = transitions.get(pair)
    attempts = attempts_of(stats) if stats is not None else 0
    mastered = (
        attempts >= min_attempts
        and transition_confidence_of(
            pair.prev_cp,
            pair.next_cp,
            transitions,
            target,
            min_attempts=min_attempts,
        )
        >= threshold
    )
    return mastered or (stall_attempts_cap is not None and attempts >= stall_attempts_cap)


def newest_key_transition_gate_progress(
    unlocked: Sequence[int],
    transitions: Mapping[Bigram, TransitionStats],
    target: float,
    key_stats: Mapping[int, KeyStats] | None,
    *,
    threshold: float = 1.0,
    min_attempts: int = MIN_TRANSITION_CONFIDENCE_ATTEMPTS,
    stall_attempts_cap: int | None = None,
    cohort_limit: int = GATING_BIGRAM_LIMIT,
) -> tuple[int, int]:
    cohort = newest_key_gating_cohort(unlocked, key_stats, limit=cohort_limit)
    ready = sum(
        gating_bigram_is_ready(
            pair,
            transitions,
            target,
            threshold=threshold,
            min_attempts=min_attempts,
            stall_attempts_cap=stall_attempts_cap,
        )
        for pair in cohort
    )
    return ready, len(cohort)


def _key_meets_unlock_threshold(
    codepoint: int,
    stats: Mapping[int, KeyStats],
    target: float,
    *,
    threshold: float,
    min_attempts: int,
) -> bool:
    """Performance (skill) and evidence (attempts) — ramp affects display only."""
    return clears_threshold(
        stats.get(codepoint), target, threshold=threshold, min_attempts=min_attempts
    )


def compute_unlocked(
    learn_order: Sequence[int],
    alphabet_size: int,
    stats: Mapping[int, KeyStats],
    target: float,
    *,
    threshold: float = 1.0,
    min_attempts: int = MIN_CONFIDENCE_ATTEMPTS,
    transitions: Mapping[Bigram, TransitionStats] | None = None,
    transition_threshold: float = 1.0,
    transition_min_attempts: int = MIN_TRANSITION_CONFIDENCE_ATTEMPTS,
    transition_stall_attempts_cap: int | None = None,
    gating_bigram_limit: int = GATING_BIGRAM_LIMIT,
) -> tuple[int, ...]:
    """The first `alphabet_size` keys are always unlocked; each further key in
    `learn_order` unlocks only once every currently-unlocked key meets skill
    ``threshold`` with at least ``min_attempts`` presses in window.

    When `transitions` is given, a further key also waits on the current
    last-unlocked key's bounded cross-key bigram cohort
    (`newest_key_clears_transition_gate`) — a little bigram practice before
    the next letter opens, bounded by `gating_bigram_limit` so the bar doesn't
    grow with alphabet depth. Pass `None` (the default) to skip this and unlock purely
    on solo-key mastery, as before."""
    forced_count = min(alphabet_size, len(learn_order))
    unlocked = list(learn_order[:forced_count])
    for codepoint in learn_order[forced_count:]:
        if not all(
            _key_meets_unlock_threshold(
                k,
                stats,
                target,
                threshold=threshold,
                min_attempts=min_attempts,
            )
            for k in unlocked
        ):
            break
        if transitions is not None and not newest_key_clears_transition_gate(
            unlocked,
            transitions,
            target,
            stats,
            threshold=transition_threshold,
            min_attempts=transition_min_attempts,
            stall_attempts_cap=transition_stall_attempts_cap,
            cohort_limit=gating_bigram_limit,
        ):
            break
        unlocked.append(codepoint)
    return tuple(unlocked)
