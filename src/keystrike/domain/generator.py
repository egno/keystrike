"""AdaptiveGenerator: keybr-style practice text — Markov-sampled words filtered
to the unlocked alphabet, with the focus letter guaranteed to appear at least once."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from random import Random

from .focus import FOCUS_BIGRAM_WORD_BOOST, FOCUS_WORD_BOOST
from .markov import TransitionTable
from .models import Bigram, Layout
from .word_bounds import MAX_WORD_LEN, MIN_WORD_LEN

MAX_RETRIES = 5
DEFAULT_WORD_COUNT = 12


@dataclass(frozen=True, slots=True)
class LessonWeighting:
    """Practice-weighting knobs threaded through lesson generation.

    Bundles the char/transition weighting inputs and the focus-word boosts so
    ``generate_lesson`` and its helpers take one object instead of a long,
    mutually-dependent parameter list.
    """

    char_weights: Mapping[str, float] | None = None
    transition_weights: Mapping[Bigram, float] | None = None
    layout: Layout | None = None
    words: tuple[str, ...] | None = None
    focus_word_boost: float = FOCUS_WORD_BOOST
    focus_bigram_word_boost: float = FOCUS_BIGRAM_WORD_BOOST

    def __post_init__(self) -> None:
        # Freezing the dataclass only blocks attribute rebinding — wrap the
        # list field too so in-place mutation of its contents also raises.
        if self.words is not None:
            object.__setattr__(self, "words", tuple(self.words))


@dataclass(frozen=True, slots=True)
class WeightedWordlist:
    """A wordlist paired with its precomputed per-word sampling weight.

    Built once per lesson (weights depend on the fixed focus char/bigram for
    that lesson) so ``words`` and ``weights`` can't drift out of index
    alignment the way two independently-threaded parallel lists could.
    """

    words: tuple[str, ...]
    weights: tuple[float, ...]


def wordlist_weight_for_word(
    word: str,
    *,
    weighting: LessonWeighting | None = None,
    focus_char: str | None = None,
    focus_bigram: str | None = None,
) -> float:
    """Score a dictionary word for adaptive sampling — mirrors Markov biasing."""
    weighting = weighting or LessonWeighting()
    char_weights = weighting.char_weights
    transition_weights = weighting.transition_weights
    if not char_weights and not transition_weights:
        return 1.0
    weight = 1.0
    if char_weights:
        weight = sum(char_weights.get(ch, 1.0) for ch in word)
    if transition_weights and len(word) > 1:
        bigram_weight = sum(
            transition_weights.get(Bigram(ord(word[i]), ord(word[i + 1])), 1.0)
            for i in range(len(word) - 1)
        )
        weight = bigram_weight if not char_weights else weight * bigram_weight
    if focus_bigram and focus_bigram in word:
        weight *= weighting.focus_bigram_word_boost
    elif focus_char and focus_char in word:
        weight *= weighting.focus_word_boost
    return weight


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
        weighting: LessonWeighting | None = None,
        *,
        weighted_wordlist: WeightedWordlist | None = None,
    ) -> str:
        weighting = weighting or LessonWeighting()
        if weighting.words:
            word = self._generate_word_from_wordlist(alphabet, weighting, weighted_wordlist)
            if word is not None:
                return word
        return self._generate_word_via_markov(alphabet, weighting)

    def _generate_word_from_wordlist(
        self,
        alphabet: frozenset[str],
        weighting: LessonWeighting,
        weighted_wordlist: WeightedWordlist | None,
    ) -> str | None:
        """Sample a dictionary word, or None if it doesn't fit length/alphabet bounds."""
        word = self._sample_from_wordlist(weighting, weighted_wordlist)
        if MIN_WORD_LEN <= len(word) <= MAX_WORD_LEN and set(word) <= alphabet:
            return word
        return None

    def _generate_word_via_markov(
        self,
        alphabet: frozenset[str],
        weighting: LessonWeighting,
    ) -> str:
        word = ""
        for _ in range(MAX_RETRIES):
            word = self._sample_word(alphabet, weighting)
            if MIN_WORD_LEN <= len(word) <= MAX_WORD_LEN:
                return word
        return word

    def generate_lesson(
        self,
        alphabet: frozenset[str],
        focus_char: str,
        *,
        word_count: int = DEFAULT_WORD_COUNT,
        weighting: LessonWeighting | None = None,
        focus_bigram: Bigram | None = None,
    ) -> str:
        weighting = weighting or LessonWeighting()
        focus_bigram_str: str | None = None
        if focus_bigram is not None:
            focus_bigram_str = focus_bigram.chars()
        weighted_wordlist: WeightedWordlist | None = None
        if weighting.words and (weighting.char_weights or weighting.transition_weights):
            weighted_wordlist = WeightedWordlist(
                words=weighting.words,
                weights=tuple(
                    wordlist_weight_for_word(
                        w,
                        weighting=weighting,
                        focus_char=focus_char,
                        focus_bigram=focus_bigram_str,
                    )
                    for w in weighting.words
                ),
            )
        lesson_words = [
            self.generate_word(alphabet, weighting, weighted_wordlist=weighted_wordlist)
            for _ in range(word_count)
        ]
        if focus_bigram is not None:
            prev_char, next_char = chr(focus_bigram.prev_cp), chr(focus_bigram.next_cp)
            bigram = prev_char + next_char
            if not any(bigram in w for w in lesson_words):
                idx = self.rng.randrange(len(lesson_words))
                lesson_words[idx] = self._inject_focus_bigram(
                    lesson_words[idx],
                    prev_char,
                    next_char,
                )
        elif not any(focus_char in w for w in lesson_words):
            idx = self.rng.randrange(len(lesson_words))
            lesson_words[idx] = self._inject_focus(lesson_words[idx], focus_char)
        return " ".join(lesson_words)

    def _sample_from_wordlist(
        self,
        weighting: LessonWeighting,
        weighted_wordlist: WeightedWordlist | None = None,
    ) -> str:
        if weighted_wordlist is not None:
            return self.rng.choices(
                weighted_wordlist.words, weights=weighted_wordlist.weights, k=1
            )[0]
        words = weighting.words or []
        if not weighting.char_weights and not weighting.transition_weights:
            return self.rng.choice(words)
        weights = [wordlist_weight_for_word(w, weighting=weighting) for w in words]
        return self.rng.choices(words, weights=weights, k=1)[0]

    def _sample_word(
        self,
        alphabet: frozenset[str],
        weighting: LessonWeighting,
    ) -> str:
        chars: list[str] = []
        while len(chars) < MAX_WORD_LEN:
            p_stop = min(1.0, 1.3 ** len(chars) / MAX_WORD_LEN)
            if chars and self.rng.random() < p_stop:
                break
            ch = self.table.sample(
                "".join(chars),
                alphabet,
                self.rng,
                char_weights=weighting.char_weights,
                layout=weighting.layout,
                transition_weights=weighting.transition_weights,
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
