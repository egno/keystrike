"""AdaptiveGenerator: keybr-style practice text — Markov-sampled words filtered
to the unlocked alphabet, with the focus letter guaranteed to appear at least once."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from random import Random

from .markov import TransitionTable
from .models import Layout

MIN_WORD_LEN = 3
MAX_WORD_LEN = 10
MAX_RETRIES = 5
DEFAULT_WORD_COUNT = 12


@dataclass(slots=True)
class AdaptiveGenerator:
    table: TransitionTable
    rng: Random

    def generate_word(
        self,
        alphabet: frozenset[str],
        char_weights: Mapping[str, float] | None = None,
        layout: Layout | None = None,
        transition_weights: Mapping[str, float] | None = None,
    ) -> str:
        word = ""
        for _ in range(MAX_RETRIES):
            word = self._sample_word(alphabet, char_weights, layout, transition_weights)
            if MIN_WORD_LEN <= len(word) <= MAX_WORD_LEN:
                return word
        return word

    def generate_lesson(
        self,
        alphabet: frozenset[str],
        focus_char: str,
        word_count: int = DEFAULT_WORD_COUNT,
        char_weights: Mapping[str, float] | None = None,
        layout: Layout | None = None,
        transition_weights: Mapping[str, float] | None = None,
    ) -> str:
        words = [
            self.generate_word(alphabet, char_weights, layout, transition_weights)
            for _ in range(word_count)
        ]
        if not any(focus_char in w for w in words):
            idx = self.rng.randrange(len(words))
            words[idx] = self._inject_focus(words[idx], focus_char)
        return " ".join(words)

    def _sample_word(
        self,
        alphabet: frozenset[str],
        char_weights: Mapping[str, float] | None,
        layout: Layout | None,
        transition_weights: Mapping[str, float] | None,
    ) -> str:
        chars: list[str] = []
        while len(chars) < MAX_WORD_LEN:
            p_stop = min(1.0, 1.3**len(chars) / MAX_WORD_LEN)
            if chars and self.rng.random() < p_stop:
                break
            ch = self.table.sample(
                "".join(chars), alphabet, self.rng, char_weights, layout, transition_weights,
            )
            if ch is None:
                ch = self.rng.choice(sorted(alphabet))
            chars.append(ch)
        return "".join(chars)

    def _inject_focus(self, word: str, focus_char: str) -> str:
        if not word:
            return focus_char
        pos = self.rng.randrange(len(word))
        return word[:pos] + focus_char + word[pos + 1 :]
