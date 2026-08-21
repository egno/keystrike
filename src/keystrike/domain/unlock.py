"""Key-unlock policy: which keys in `learn_order` are currently unlocked,
gated on per-key skill and attempt floor, plus (optionally) the newest key's
single weakest bigram (§6 of PLAN.md)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from .confidence import attempts_of, clears_threshold, transition_confidence_of
from .models import Bigram, KeyStats, TransitionStats, UnlockTuning
from .newest_key import newest_key_gating_cohort

# ponytail: fixed multiplier; upgrade to a Settings field if a stuck gating
# bigram turns out to need per-user tuning.
TRANSITION_STALL_ATTEMPTS_MULTIPLIER = 3

_DEFAULT_UNLOCK_TUNING = UnlockTuning()


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
    tuning: UnlockTuning = _DEFAULT_UNLOCK_TUNING,
    stall_attempts_cap: int | None = None,
) -> bool:
    """Whether every member of the newest key's bounded cohort is ready."""
    ready, total = newest_key_transition_gate_progress(
        unlocked,
        transitions,
        target,
        key_stats,
        tuning=tuning,
        stall_attempts_cap=stall_attempts_cap,
    )
    return ready == total


def gating_bigram_is_ready(
    pair: Bigram,
    transitions: Mapping[Bigram, TransitionStats],
    target: float,
    *,
    tuning: UnlockTuning = _DEFAULT_UNLOCK_TUNING,
    stall_attempts_cap: int | None = None,
) -> bool:
    stats = transitions.get(pair)
    attempts = attempts_of(stats) if stats is not None else 0
    mastered = (
        attempts >= tuning.min_transition_confidence_attempts
        and transition_confidence_of(
            pair.prev_cp,
            pair.next_cp,
            transitions,
            target,
            min_attempts=tuning.min_transition_confidence_attempts,
        )
        >= tuning.next_letter_unlock_threshold
    )
    return mastered or (stall_attempts_cap is not None and attempts >= stall_attempts_cap)


def newest_key_transition_gate_progress(
    unlocked: Sequence[int],
    transitions: Mapping[Bigram, TransitionStats],
    target: float,
    key_stats: Mapping[int, KeyStats] | None,
    *,
    tuning: UnlockTuning = _DEFAULT_UNLOCK_TUNING,
    stall_attempts_cap: int | None = None,
) -> tuple[int, int]:
    cohort = newest_key_gating_cohort(unlocked, key_stats, limit=tuning.gating_bigram_limit)
    ready = sum(
        gating_bigram_is_ready(
            pair,
            transitions,
            target,
            tuning=tuning,
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
    tuning: UnlockTuning = _DEFAULT_UNLOCK_TUNING,
    transitions: Mapping[Bigram, TransitionStats] | None = None,
    transition_stall_attempts_cap: int | None = None,
) -> tuple[int, ...]:
    """The first `alphabet_size` keys are always unlocked; each further key in
    `learn_order` unlocks only once every currently-unlocked key meets skill
    ``tuning.next_letter_unlock_threshold`` with at least
    ``tuning.min_confidence_attempts`` presses in window.

    When `transitions` is given, a further key also waits on the current
    last-unlocked key's bounded cross-key bigram cohort
    (`newest_key_clears_transition_gate`) — a little bigram practice before
    the next letter opens, bounded by `tuning.gating_bigram_limit` so the bar
    doesn't grow with alphabet depth. Pass `None` (the default) to skip this
    and unlock purely on solo-key mastery, as before.

    The result can exceed `alphabet_size` once mastery conditions are met --
    `alphabet_size` is a floor, not a cap. Callers that persist a Settings
    object should feed the result through
    `application.alphabet_sync.sync_alphabet_size` so the setting never lags
    behind what's actually unlocked (see `build_lesson._gating_state` and
    `session_use_cases.FinishSession` for the two call sites)."""
    forced_count = min(alphabet_size, len(learn_order))
    unlocked = list(learn_order[:forced_count])
    for codepoint in learn_order[forced_count:]:
        if not all(
            _key_meets_unlock_threshold(
                k,
                stats,
                target,
                threshold=tuning.next_letter_unlock_threshold,
                min_attempts=tuning.min_confidence_attempts,
            )
            for k in unlocked
        ):
            break
        if transitions is not None and not newest_key_clears_transition_gate(
            unlocked,
            transitions,
            target,
            stats,
            tuning=tuning,
            stall_attempts_cap=transition_stall_attempts_cap,
        ):
            break
        unlocked.append(codepoint)
    return tuple(unlocked)
