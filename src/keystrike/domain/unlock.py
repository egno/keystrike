"""Key-unlock policy: which keys in `learn_order` are currently unlocked,
gated on per-key skill and attempt floor, plus (optionally) the newest key's
single weakest bigram (§6 of PLAN.md)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from .confidence import (
    MIN_CONFIDENCE_ATTEMPTS,
    MIN_TRANSITION_CONFIDENCE_ATTEMPTS,
    attempts_of,
    skill_of,
    transition_confidence_of,
)
from .models import Bigram, KeyStats, TransitionStats
from .newest_key import newest_practiced_key_pairs

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
) -> bool:
    """Whether the most-recently-*practiced* unlocked key's bigrams with its
    peers are solid enough to let the next key open — the unlock half of
    `compute_unlocked`'s transition gate.

    Built on `domain.newest_key.newest_practiced_key_pairs`, the same split
    `domain.focus.newest_key_unmeasured_pairs` uses for focus selection, so
    gating and focus never disagree on what "newest" means. While that key
    has *no* measured pair with any peer yet, the gate simply isn't clear
    (nothing to release on — lesson weighting is already pushing the user to
    type one). Once it has *any* measured pair, only measured pairs are
    weighed against each other — an untouched peer pair no longer counts
    against it, so this can never regress into requiring every combinatorial
    pair, only whichever ones have actually been engaged with (bounded,
    "weakest of what's been tried so far", not "weakest of everything
    possible").

    `stall_attempts_cap` is a safety valve: a measured pair stuck below
    threshold no matter how much it's drilled would otherwise block
    progression forever. Once its attempts pass the cap, the gate clears
    anyway. Because the weakest candidate is always drawn from *measured*
    pairs, it always has real attempt data to check the cap against."""
    unmeasured, measured = newest_practiced_key_pairs(unlocked, transitions, key_stats)
    if not unmeasured and not measured:
        return True
    if not measured:
        return False
    weakest = min(
        measured,
        key=lambda p: transition_confidence_of(
            p.prev_cp, p.next_cp, transitions, target, min_attempts=min_attempts
        ),
    )
    weakest_confidence = transition_confidence_of(
        weakest.prev_cp, weakest.next_cp, transitions, target, min_attempts=min_attempts
    )
    if weakest_confidence >= threshold:
        return True
    if stall_attempts_cap is None:
        return False
    return attempts_of(transitions[weakest]) >= stall_attempts_cap


def _key_meets_unlock_threshold(
    codepoint: int,
    stats: Mapping[int, KeyStats],
    target: float,
    *,
    threshold: float,
    min_attempts: int,
) -> bool:
    """Performance (skill) and evidence (attempts) — ramp affects display only."""
    key_stats = stats.get(codepoint)
    if key_stats is None:
        return False
    return (
        skill_of(codepoint, stats, target) >= threshold and attempts_of(key_stats) >= min_attempts
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
) -> tuple[int, ...]:
    """The first `alphabet_size` keys are always unlocked; each further key in
    `learn_order` unlocks only once every currently-unlocked key meets skill
    ``threshold`` with at least ``min_attempts`` presses in window.

    When `transitions` is given, a further key also waits on the current
    last-unlocked key's single weakest cross-key bigram
    (`newest_key_clears_transition_gate`) — a little bigram practice before
    the next letter opens, bounded to one pair so the bar doesn't grow with
    alphabet depth. Pass `None` (the default) to skip this and unlock purely
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
        ):
            break
        unlocked.append(codepoint)
    return tuple(unlocked)
