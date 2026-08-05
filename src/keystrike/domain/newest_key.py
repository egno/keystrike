"""Shared "what does the newest unlocked key still need bigram attention on"
primitives.

Used by both `domain.focus` (focus selection, lesson weighting) and
`domain.unlock` (the transition gate) — kept in a neutral module so neither
has to import the other's policy: focus selection isn't an unlock concern,
and unlock gating isn't a focus concern, but both need to agree on the same
"newest practiced key" and "its cross-key pairs" definitions."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from .confidence import is_same_key_transition
from .models import GATING_BIGRAM_LIMIT, Bigram, KeyStats, TransitionStats

_GATING_BIGRAM_MIN = 2
_GATING_BIGRAM_MAX = 4


def effective_gating_bigram_limit(limit: int) -> int:
    """Clamp hand-edited settings to the supported bounded cohort size."""
    return min(_GATING_BIGRAM_MAX, max(_GATING_BIGRAM_MIN, limit))


def unlocked_cross_key_pairs(unlocked: Sequence[int]) -> list[Bigram]:
    """All directed cross-key pairs among currently-unlocked keys (same-key
    pairs like `aa` excluded — see `is_same_key_transition`)."""
    return [
        Bigram(prev, nxt)
        for prev in unlocked
        for nxt in unlocked
        if not is_same_key_transition(prev, nxt)
    ]


def newest_practiced_key_pairs(
    unlocked: Sequence[int],
    transitions: Mapping[Bigram, TransitionStats],
    key_stats: Mapping[int, KeyStats] | None,
) -> tuple[list[Bigram], list[Bigram]]:
    """(unmeasured, measured) cross-key pairs between the most-recently-
    *practiced* unlocked key (skipping any further, not-yet-touched key
    added by an unlock-threshold cascade) and its other already-practiced
    unlocked peers. Both empty when no unlocked key has been practiced yet,
    or the newest practiced key has no practiced peer to pair with.

    Single source of truth for "what does the newest key still need bigram
    attention on" — shared by `domain.focus.newest_key_unmeasured_pairs`
    (focus selection, lesson weighting) and
    `domain.unlock.newest_key_clears_transition_gate` (unlock), so the two
    can't drift on what counts as newest or which pairs are in play."""
    practiced = [cp for cp in unlocked if key_stats is not None and cp in key_stats]
    if not practiced:
        return [], []
    newest = practiced[-1]
    practiced_set = frozenset(practiced)
    pairs = [
        pair
        for pair in unlocked_cross_key_pairs(unlocked)
        if newest in (pair.prev_cp, pair.next_cp)
        and pair.prev_cp in practiced_set
        and pair.next_cp in practiced_set
    ]
    measured = [pair for pair in pairs if pair in transitions]
    unmeasured = [pair for pair in pairs if pair not in transitions]
    return unmeasured, measured


def newest_key_gating_cohort(
    unlocked: Sequence[int],
    key_stats: Mapping[int, KeyStats] | None,
    *,
    limit: int = GATING_BIGRAM_LIMIT,
) -> tuple[Bigram, ...]:
    """Stable 2-4 directed bigrams for the newest practiced key.

    Pair it bidirectionally with at most its two most-recent practiced peers.
    The cohort depends only on learn/unlock order and which keys have been
    practiced, so incidental transition measurements cannot expand or replace
    it while the letter is being calibrated.
    """
    practiced = [cp for cp in unlocked if key_stats is not None and cp in key_stats]
    if len(practiced) < _GATING_BIGRAM_MIN:
        return ()
    newest = practiced[-1]
    peers = practiced[-3:-1]
    cohort = tuple(pair for peer in peers for pair in (Bigram(peer, newest), Bigram(newest, peer)))
    return cohort[-effective_gating_bigram_limit(limit) :]
