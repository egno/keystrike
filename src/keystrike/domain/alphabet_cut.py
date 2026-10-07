"""Forget the stats of keys the user closed by lowering `alphabet_size`.

When the user lowers `alphabet_size`, the closed keys keep their old stats.
Without a cut those stats would reopen the keys at once, with no new
practice. An `AlphabetCut` records the decrease; `forget_closed_keys` drops
the closed keys' tallies (and every bigram that touches them) from sessions
recorded before it. A reopened key then goes through the whole lesson
ladder again — key focus, then its gate bigrams — before the next one opens.
"""

from __future__ import annotations

from collections.abc import Sequence

from .models import AlphabetCut, SessionStats


def add_alphabet_cut(cuts: Sequence[AlphabetCut], cut: AlphabetCut) -> tuple[AlphabetCut, ...]:
    """Append `cut`, dropping earlier cuts it covers (size >= `cut.size`):
    every session before them is also before `cut`, and `cut` closes more."""
    return (*(c for c in cuts if c.size < cut.size), cut)


def closed_keys(
    started_at: float,
    learn_order: Sequence[int],
    cuts: Sequence[AlphabetCut],
) -> frozenset[int]:
    """Keys whose stats from a session that started at `started_at` are forgotten."""
    sizes = [c.size for c in cuts if c.at > started_at]
    if not sizes:
        return frozenset()
    return frozenset(learn_order[min(sizes) :])


def forget_closed_keys(
    stats: SessionStats,
    started_at: float,
    learn_order: Sequence[int],
    cuts: Sequence[AlphabetCut],
) -> SessionStats:
    """`stats` without the tallies of keys closed after the session started."""
    closed = closed_keys(started_at, learn_order, cuts)
    if not closed:
        return stats
    return SessionStats(
        keys={cp: t for cp, t in stats.keys.items() if cp not in closed},
        transitions={
            pair: t
            for pair, t in stats.transitions.items()
            if pair.prev_cp not in closed and pair.next_cp not in closed
        },
    )
