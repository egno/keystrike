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
        *,
        word_count: int = DEFAULT_WORD_COUNT,
        char_weights: Mapping[str, float] | None = None,
        layout: Layout | None = None,
        transition_weights: Mapping[str, float] | None = None,
        focus_bigram: tuple[int, int] | None = None,
    ) -> str:
        words = [
            self.generate_word(alphabet, char_weights, layout, transition_weights)
            for _ in range(word_count)
        ]
        if focus_bigram is not None:
            prev_char, next_char = chr(focus_bigram[0]), chr(focus_bigram[1])
            bigram = prev_char + next_char
            if not any(bigram in w for w in words):
                idx = self.rng.randrange(len(words))
                words[idx] = self._inject_focus_bigram(words[idx], prev_char, next_char)
        elif not any(focus_char in w for w in words):
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
                "".join(chars),
                alphabet,
                self.rng,
                char_weights=char_weights,
                layout=layout,
                transition_weights=transition_weights,
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

    def _inject_focus_bigram(self, word: str, prev_char: str, next_char: str) -> str:
        bigram = prev_char + next_char
        if bigram in word:
            return word
        if not word:
            return bigram
        if len(word) == 1:
            return prev_char + next_char if word != prev_char else word + next_char
        pos = self.rng.randrange(len(word) - 1)
        return word[:pos] + prev_char + next_char + word[pos + 2 :]
