"""Order-N Markov transition table + weighted sampler, filtered to a caller-supplied
alphabet (the adaptive engine's unlocked-key set)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from random import Random
from types import MappingProxyType

from .models import Bigram, Layout

_DIFFERENT_HAND_BOOST = 1.5
_DIFFERENT_FINGER_SAME_HAND_BOOST = 1.2


def transition_practice_weight(prev_cp: int, next_cp: int, layout: Layout) -> float:
    """Ergonomics bias for bigram transitions during practice text sampling."""
    prev = layout.keys.get(prev_cp)
    nxt = layout.keys.get(next_cp)
    if prev is None or nxt is None:
        return 1.0
    if prev.hand != nxt.hand:
        return _DIFFERENT_HAND_BOOST
    if prev.finger != nxt.finger:
        return _DIFFERENT_FINGER_SAME_HAND_BOOST
    return 1.0


@dataclass(frozen=True, slots=True)
class TransitionTable:
    order: int
    transitions: Mapping[str, Mapping[str, int]]  # context -> next_char -> weight

    def __post_init__(self) -> None:
        # Freezing the dataclass only blocks attribute rebinding — wrap the
        # dict field too so in-place mutation of its contents also raises.
        object.__setattr__(self, "transitions", MappingProxyType(dict(self.transitions)))

    def sample(
        self,
        context: str,
        alphabet: frozenset[str],
        rng: Random,
        *,
        char_weights: Mapping[str, float] | None = None,
        layout: Layout | None = None,
        transition_weights: Mapping[Bigram, float] | None = None,
    ) -> str | None:
        """Sample the next char given `context`, restricted to `alphabet`.

        Backs off from the full-order context to shorter ones (and finally the
        global "" distribution) until it finds a row with at least one
        candidate in `alphabet`. Returns None if nothing usable exists.

        `char_weights` (e.g. from `confidence.practice_weight`) multiplies each
        candidate's language-frequency weight, so callers can bias sampling
        toward specific chars (weak keys) without abandoning natural bigram
        frequencies entirely.

        When `layout` is set, each candidate is also scaled by
        `transition_practice_weight` from the last char in `context`.

        `transition_weights` (keyed by `Bigram(prev_cp, next_cp)`) multiplies
        each candidate by the learner's measured confidence on that pair.
        """
        prev_cp = ord(context[-1]) if context else None
        max_len = min(self.order, len(context))
        for length in range(max_len, -1, -1):
            ctx = context[len(context) - length :] if length else ""
            row = self.transitions.get(ctx)
            if not row:
                continue
            candidates = [(ch, weight) for ch, weight in row.items() if ch in alphabet]
            if not candidates:
                continue
            chars = [c for c, _ in candidates]
            if char_weights or layout or transition_weights:
                weights = []
                for c, w in candidates:
                    weight = w * (char_weights.get(c, 1.0) if char_weights else 1.0)
                    if layout is not None and prev_cp is not None:
                        weight *= transition_practice_weight(prev_cp, ord(c), layout)
                    if transition_weights is not None and prev_cp is not None:
                        weight *= transition_weights.get(Bigram(prev_cp, ord(c)), 1.0)
                    weights.append(weight)
            else:
                weights = [w for _, w in candidates]
            return rng.choices(chars, weights=weights, k=1)[0]
        return None
