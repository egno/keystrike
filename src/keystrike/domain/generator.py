"""AdaptiveGenerator: keybr-style practice text — Markov-sampled words filtered
to the unlocked alphabet, with the focus letter guaranteed to appear at least once."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from random import Random

from .markov import TransitionTable
from .models import Layout
from .word_bounds import MAX_WORD_LEN, MIN_WORD_LEN

MAX_RETRIES = 5
DEFAULT_WORD_COUNT = 12


def typical_chars_per_word() -> float:
    """Mean chars per generated word (spaces excluded).

    ponytail: midpoint of accepted word lengths; upgrade to measured corpus avg.
    """
    return (MIN_WORD_LEN + MAX_WORD_LEN) / 2.0


def cpm_from_wpm(wpm: int) -> int:
    return round(wpm * typical_chars_per_word())


def wpm_from_cpm(cpm: int) -> int:
    return int(cpm / typical_chars_per_word())


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
        *,
        words: list[str] | None = None,
        wordlist_weights: list[float] | None = None,
    ) -> str:
        if words:
            word = self._sample_from_wordlist(words, char_weights, wordlist_weights)
            if (
                MIN_WORD_LEN <= len(word) <= MAX_WORD_LEN
                and set(word) <= alphabet
            ):
                return word
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
        words: list[str] | None = None,
    ) -> str:
        wordlist_weights: list[float] | None = None
        if words and char_weights:
            wordlist_weights = [
                sum(char_weights.get(ch, 1.0) for ch in w) for w in words
            ]
        lesson_words = [
            self.generate_word(
                alphabet,
                char_weights,
                layout,
                transition_weights,
                words=words,
                wordlist_weights=wordlist_weights,
            )
            for _ in range(word_count)
        ]
        if focus_bigram is not None:
            prev_char, next_char = chr(focus_bigram[0]), chr(focus_bigram[1])
            bigram = prev_char + next_char
            if not any(bigram in w for w in lesson_words):
                idx = self.rng.randrange(len(lesson_words))
                lesson_words[idx] = self._inject_focus_bigram(
                    lesson_words[idx], prev_char, next_char,
                )
        elif not any(focus_char in w for w in lesson_words):
            idx = self.rng.randrange(len(lesson_words))
            lesson_words[idx] = self._inject_focus(lesson_words[idx], focus_char)
        return " ".join(lesson_words)

    def _sample_from_wordlist(
        self,
        words: list[str],
        char_weights: Mapping[str, float] | None,
        wordlist_weights: list[float] | None = None,
    ) -> str:
        if wordlist_weights is not None:
            return self.rng.choices(words, weights=wordlist_weights, k=1)[0]
        if not char_weights:
            return self.rng.choice(words)
        weights = [sum(char_weights.get(ch, 1.0) for ch in w) for w in words]
        return self.rng.choices(words, weights=weights, k=1)[0]

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
