"""Order-N Markov transition table + weighted sampler, filtered to a caller-supplied
alphabet (the adaptive engine's unlocked-key set)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from random import Random


@dataclass(frozen=True, slots=True)
class TransitionTable:
    order: int
    transitions: Mapping[str, Mapping[str, int]]  # context -> next_char -> weight

    def sample(
        self,
        context: str,
        alphabet: frozenset[str],
        rng: Random,
        char_weights: Mapping[str, float] | None = None,
    ) -> str | None:
        """Sample the next char given `context`, restricted to `alphabet`.

        Backs off from the full-order context to shorter ones (and finally the
        global "" distribution) until it finds a row with at least one
        candidate in `alphabet`. Returns None if nothing usable exists.

        `char_weights` (e.g. from `confidence.practice_weight`) multiplies each
        candidate's language-frequency weight, so callers can bias sampling
        toward specific chars (weak keys) without abandoning natural bigram
        frequencies entirely.
        """
        max_len = min(self.order, len(context))
        for length in range(max_len, -1, -1):
            ctx = context[len(context) - length:] if length else ""
            row = self.transitions.get(ctx)
            if not row:
                continue
            candidates = [(ch, weight) for ch, weight in row.items() if ch in alphabet]
            if not candidates:
                continue
            chars = [c for c, _ in candidates]
            if char_weights:
                weights = [w * char_weights.get(c, 1.0) for c, w in candidates]
            else:
                weights = [w for _, w in candidates]
            return rng.choices(chars, weights=weights, k=1)[0]
        return None
