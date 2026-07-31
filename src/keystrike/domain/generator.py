"""AdaptiveGenerator: keybr-style practice text — Markov-sampled words filtered
to the unlocked alphabet, with the focus letter guaranteed to appear at least once."""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from random import Random

from .focus import FOCUS_BIGRAM_WORD_BOOST, FOCUS_WORD_BOOST
from .markov import TransitionTable
from .models import (
    FOCUS_WORD_MIN_FRACTION,
    GENERATED_WORD_MAX_LEN,
    GENERATED_WORD_MIN_LEN,
    MAX_WORD_REPEATS,
    Bigram,
    Layout,
)
from .models import (
    LESSON_WORD_COUNT as DEFAULT_WORD_COUNT,
)

MAX_RETRIES = 5
MAX_REPEAT_RESAMPLE = 64


def min_focus_words(word_count: int, fraction: float = FOCUS_WORD_MIN_FRACTION) -> int:
    """Minimum focus-matching words required for weak-focus lessons."""
    return math.ceil(word_count * fraction)


def clamp_focus_word_fraction(fraction: float) -> float:
    """Keep hand-edited settings.toml values within (0, 1]."""
    return min(1.0, max(0.0, fraction))


def weak_focus_word_quota(word_count: int, fraction: float) -> int:
    """Weak-focus slot count that satisfies ``generate_lesson`` preconditions."""
    return min(min_focus_words(word_count, clamp_focus_word_fraction(fraction)), word_count)


def effective_max_word_repeats(max_repeats: int) -> int:
    """Per-lesson repeat cap must be at least 1 or no word can be appended."""
    return max(1, max_repeats)


def effective_lesson_word_count(word_count: int) -> int:
    """Hand-edited settings may set 0; practice needs at least one word."""
    return max(1, word_count)


def effective_generated_word_bounds(min_len: int, max_len: int) -> tuple[int, int]:
    """Clamp hand-edited settings; ensure min <= max and both are at least 1."""
    min_len = max(1, min_len)
    max_len = max(1, max_len)
    min_len = min(min_len, max_len)
    return min_len, max_len


def word_matches_focus(
    word: str,
    *,
    focus_char: str,
    focus_bigram: str | None,
) -> bool:
    """True when word satisfies the active focus criterion."""
    if focus_bigram is not None:
        return focus_bigram in word
    return focus_char in word


def _assert_lesson_focus_quota(
    words: list[str],
    *,
    min_focus_words: int,
    focus_char: str,
    focus_bigram: str | None,
) -> None:
    """Ensures: when min_focus_words > 1, at least that many words match focus."""
    if min_focus_words <= 1:
        return
    matching = sum(
        1 for w in words if word_matches_focus(w, focus_char=focus_char, focus_bigram=focus_bigram)
    )
    assert matching >= min_focus_words, (
        f"focus quota unmet: {matching}/{len(words)} words match (required {min_focus_words})"
    )


def _wordlist_word_fits(
    word: str,
    alphabet: frozenset[str],
    *,
    min_len: int,
    max_len: int,
) -> bool:
    """True when ``word`` length is in ``[min_len, max_len]`` and chars ⊆ alphabet."""
    return min_len <= len(word) <= max_len and set(word) <= alphabet


def _focus_pool_from_wordlist(
    words: tuple[str, ...] | None,
    alphabet: frozenset[str],
    *,
    focus_char: str,
    focus_bigram: str | None,
    generated_min_len: int,
    generated_max_len: int,
) -> tuple[str, ...]:
    if not words:
        return ()
    return tuple(
        w
        for w in words
        if _wordlist_word_fits(
            w,
            alphabet,
            min_len=generated_min_len,
            max_len=generated_max_len,
        )
        and word_matches_focus(w, focus_char=focus_char, focus_bigram=focus_bigram)
    )


def _sample_focus_words_without_replacement(
    rng: Random,
    focus_pool: tuple[str, ...],
    focus_weighted: WeightedWordlist | None,
    count: int,
) -> list[str]:
    """Draw up to ``count`` distinct focus-pool words without replacement.

    Ensures: returned words are unique, each from ``focus_pool``,
    len <= min(count, len(focus_pool)).
    """
    if count <= 0 or not focus_pool:
        return []
    pool = list(focus_pool)
    weights = list(focus_weighted.weights) if focus_weighted is not None else [1.0] * len(pool)
    sampled: list[str] = []
    for _ in range(min(count, len(pool))):
        word = rng.choices(pool, weights=weights, k=1)[0]
        idx = pool.index(word)
        sampled.append(word)
        pool.pop(idx)
        weights.pop(idx)
    return sampled


def _append_word_if_under_repeat_cap(
    lesson_words: list[str],
    word: str,
    *,
    max_repeats: int = MAX_WORD_REPEATS,
) -> bool:
    """Append ``word`` when it would stay under the per-lesson repeat cap."""
    if Counter(lesson_words)[word] >= max_repeats:
        return False
    lesson_words.append(word)
    return True


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


def typical_chars_per_word(
    *,
    generated_min_len: int = GENERATED_WORD_MIN_LEN,
    generated_max_len: int = GENERATED_WORD_MAX_LEN,
) -> float:
    """Mean chars per generated word (spaces excluded).

    ponytail: midpoint of accepted word lengths; upgrade to measured corpus avg.
    """
    min_len, max_len = effective_generated_word_bounds(generated_min_len, generated_max_len)
    return (min_len + max_len) / 2.0


def cpm_from_wpm(
    wpm: int,
    *,
    generated_min_len: int = GENERATED_WORD_MIN_LEN,
    generated_max_len: int = GENERATED_WORD_MAX_LEN,
) -> int:
    return round(
        wpm
        * typical_chars_per_word(
            generated_min_len=generated_min_len,
            generated_max_len=generated_max_len,
        )
    )


def wpm_from_cpm(
    cpm: int,
    *,
    generated_min_len: int = GENERATED_WORD_MIN_LEN,
    generated_max_len: int = GENERATED_WORD_MAX_LEN,
) -> int:
    return int(
        cpm
        / typical_chars_per_word(
            generated_min_len=generated_min_len,
            generated_max_len=generated_max_len,
        )
    )


def _ensure_generated_word_len(
    word: str,
    alphabet: frozenset[str],
    rng: Random,
    *,
    generated_min_len: int,
    generated_max_len: int,
) -> str:
    """Pad or trim ``word`` into ``[generated_min_len, generated_max_len]``."""
    chars = sorted(alphabet)
    if not chars:
        return word
    if not word:
        word = "".join(rng.choice(chars) for _ in range(generated_min_len))
    while len(word) < generated_min_len:
        word += rng.choice(chars)
    if len(word) > generated_max_len:
        word = word[:generated_max_len]
    return word


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
        generated_min_len: int = GENERATED_WORD_MIN_LEN,
        generated_max_len: int = GENERATED_WORD_MAX_LEN,
    ) -> str:
        weighting = weighting or LessonWeighting()
        if weighting.words:
            word = self._generate_word_from_wordlist(
                alphabet,
                weighting,
                weighted_wordlist,
                generated_min_len=generated_min_len,
                generated_max_len=generated_max_len,
            )
            if word is not None:
                return word
        return self._generate_word_via_markov(
            alphabet, weighting, generated_min_len, generated_max_len
        )

    def _generate_word_from_wordlist(
        self,
        alphabet: frozenset[str],
        weighting: LessonWeighting,
        weighted_wordlist: WeightedWordlist | None,
        *,
        generated_min_len: int,
        generated_max_len: int,
    ) -> str | None:
        """Sample a dictionary word, or None if it doesn't fit length/alphabet bounds."""
        word = self._sample_from_wordlist(weighting, weighted_wordlist)
        if _wordlist_word_fits(
            word,
            alphabet,
            min_len=generated_min_len,
            max_len=generated_max_len,
        ):
            return word
        return None

    def _generate_word_via_markov(
        self,
        alphabet: frozenset[str],
        weighting: LessonWeighting,
        generated_min_len: int,
        generated_max_len: int,
    ) -> str:
        word = ""
        for _ in range(MAX_RETRIES):
            word = self._sample_word(alphabet, weighting, generated_max_len)
            if generated_min_len <= len(word) <= generated_max_len:
                return word
        return _ensure_generated_word_len(
            word,
            alphabet,
            self.rng,
            generated_min_len=generated_min_len,
            generated_max_len=generated_max_len,
        )

    def generate_lesson(
        self,
        alphabet: frozenset[str],
        focus_char: str,
        *,
        word_count: int = DEFAULT_WORD_COUNT,
        weighting: LessonWeighting | None = None,
        focus_bigram: Bigram | None = None,
        min_focus_words: int = 1,
        max_word_repeats: int = MAX_WORD_REPEATS,
        generated_min_len: int = GENERATED_WORD_MIN_LEN,
        generated_max_len: int = GENERATED_WORD_MAX_LEN,
    ) -> str:
        """Generate practice text with focus-word guarantees.

        Requires: ``0 <= min_focus_words <= word_count``.
        Ensures: at least ``min_focus_words`` words match focus when ``min_focus_words > 1``;
        always at least one focus match when focus is specified.
        """
        word_count = effective_lesson_word_count(word_count)
        min_focus_words = min(min_focus_words, word_count)
        assert 0 <= min_focus_words <= word_count
        max_word_repeats = effective_max_word_repeats(max_word_repeats)
        generated_min_len, generated_max_len = effective_generated_word_bounds(
            generated_min_len, generated_max_len
        )
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
        focus_pool = _focus_pool_from_wordlist(
            weighting.words,
            alphabet,
            focus_char=focus_char,
            focus_bigram=focus_bigram_str,
            generated_min_len=generated_min_len,
            generated_max_len=generated_max_len,
        )
        focus_weighted: WeightedWordlist | None = None
        if focus_pool and weighted_wordlist is not None:
            pool_set = frozenset(focus_pool)
            focus_weighted = WeightedWordlist(
                words=focus_pool,
                weights=tuple(
                    w
                    for word, w in zip(
                        weighted_wordlist.words, weighted_wordlist.weights, strict=True
                    )
                    if word in pool_set
                ),
            )
        if min_focus_words <= 1:
            lesson_words: list[str] = []
            while len(lesson_words) < word_count:
                self._append_general_word_capped(
                    lesson_words,
                    alphabet,
                    weighting,
                    weighted_wordlist=weighted_wordlist,
                    max_word_repeats=max_word_repeats,
                    generated_min_len=generated_min_len,
                    generated_max_len=generated_max_len,
                )
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
        else:
            focus_quota = min(min_focus_words, word_count)
            lesson_words: list[str] = []
            pool_draws = _sample_focus_words_without_replacement(
                self.rng,
                focus_pool,
                focus_weighted,
                focus_quota,
            )
            for word in pool_draws:
                _append_word_if_under_repeat_cap(lesson_words, word, max_repeats=max_word_repeats)
            while (
                sum(
                    1
                    for w in lesson_words
                    if word_matches_focus(w, focus_char=focus_char, focus_bigram=focus_bigram_str)
                )
                < focus_quota
            ):
                self._append_focus_word_capped(
                    lesson_words,
                    alphabet,
                    weighting,
                    focus_char=focus_char,
                    focus_bigram=focus_bigram,
                    focus_bigram_str=focus_bigram_str,
                    use_wordlist=False,
                    max_word_repeats=max_word_repeats,
                    generated_min_len=generated_min_len,
                    generated_max_len=generated_max_len,
                )
            while len(lesson_words) < word_count:
                self._append_general_word_capped(
                    lesson_words,
                    alphabet,
                    weighting,
                    weighted_wordlist=weighted_wordlist,
                    max_word_repeats=max_word_repeats,
                    generated_min_len=generated_min_len,
                    generated_max_len=generated_max_len,
                )
            self.rng.shuffle(lesson_words)
            _assert_lesson_focus_quota(
                lesson_words,
                min_focus_words=focus_quota,
                focus_char=focus_char,
                focus_bigram=focus_bigram_str,
            )
        return " ".join(lesson_words)

    def _append_focus_word_capped(
        self,
        lesson_words: list[str],
        alphabet: frozenset[str],
        weighting: LessonWeighting,
        *,
        focus_char: str,
        focus_bigram: Bigram | None,
        focus_bigram_str: str | None,
        use_wordlist: bool,
        focus_pool: tuple[str, ...] = (),
        focus_weighted: WeightedWordlist | None = None,
        max_word_repeats: int = MAX_WORD_REPEATS,
        generated_min_len: int = GENERATED_WORD_MIN_LEN,
        generated_max_len: int = GENERATED_WORD_MAX_LEN,
    ) -> None:
        """Add one focus-matching word, respecting the per-lesson repeat cap."""
        for _ in range(MAX_REPEAT_RESAMPLE):
            word = self._generate_focus_word(
                alphabet,
                weighting,
                focus_char=focus_char,
                focus_bigram=focus_bigram,
                focus_bigram_str=focus_bigram_str,
                focus_pool=focus_pool if use_wordlist else (),
                focus_weighted=focus_weighted if use_wordlist else None,
                generated_min_len=generated_min_len,
                generated_max_len=generated_max_len,
            )
            if _append_word_if_under_repeat_cap(lesson_words, word, max_repeats=max_word_repeats):
                return
        word = self._generate_focus_word(
            alphabet,
            weighting,
            focus_char=focus_char,
            focus_bigram=focus_bigram,
            focus_bigram_str=focus_bigram_str,
            focus_pool=(),
            focus_weighted=None,
            generated_min_len=generated_min_len,
            generated_max_len=generated_max_len,
        )
        self._append_word_mutating_until_under_cap(
            lesson_words,
            word,
            alphabet,
            focus_char=focus_char,
            focus_bigram=focus_bigram,
            max_word_repeats=max_word_repeats,
            generated_max_len=generated_max_len,
        )

    def _append_general_word_capped(
        self,
        lesson_words: list[str],
        alphabet: frozenset[str],
        weighting: LessonWeighting,
        *,
        weighted_wordlist: WeightedWordlist | None,
        max_word_repeats: int = MAX_WORD_REPEATS,
        generated_min_len: int = GENERATED_WORD_MIN_LEN,
        generated_max_len: int = GENERATED_WORD_MAX_LEN,
    ) -> None:
        """Add one general word, respecting the per-lesson repeat cap."""
        for _ in range(MAX_REPEAT_RESAMPLE):
            word = self.generate_word(
                alphabet,
                weighting,
                weighted_wordlist=weighted_wordlist,
                generated_min_len=generated_min_len,
                generated_max_len=generated_max_len,
            )
            if _append_word_if_under_repeat_cap(lesson_words, word, max_repeats=max_word_repeats):
                return
        word = self.generate_word(
            alphabet,
            weighting,
            weighted_wordlist=weighted_wordlist,
            generated_min_len=generated_min_len,
            generated_max_len=generated_max_len,
        )
        self._append_word_mutating_until_under_cap(
            lesson_words,
            word,
            alphabet,
            max_word_repeats=max_word_repeats,
            generated_max_len=generated_max_len,
        )

    def _append_word_mutating_until_under_cap(
        self,
        lesson_words: list[str],
        word: str,
        alphabet: frozenset[str],
        *,
        focus_char: str | None = None,
        focus_bigram: Bigram | None = None,
        max_word_repeats: int = MAX_WORD_REPEATS,
        generated_max_len: int = GENERATED_WORD_MAX_LEN,
    ) -> None:
        """Ensures: word is appended without exceeding the repeat cap."""
        if _append_word_if_under_repeat_cap(lesson_words, word, max_repeats=max_word_repeats):
            return
        chars = sorted(alphabet)
        for _ in range(MAX_REPEAT_RESAMPLE):
            if len(word) < generated_max_len:
                word = word + self.rng.choice(chars)
            elif focus_bigram is not None:
                prev_char, next_char = chr(focus_bigram.prev_cp), chr(focus_bigram.next_cp)
                word = self._inject_focus_bigram(word, prev_char, next_char)
            elif focus_char is not None:
                word = self._inject_focus(word, focus_char)
            else:
                pos = self.rng.randrange(len(word))
                word = word[:pos] + self.rng.choice(chars) + word[pos + 1 :]
            if _append_word_if_under_repeat_cap(lesson_words, word, max_repeats=max_word_repeats):
                return
        # ponytail: small alphabet caps distinct words below lesson_word_count x max_repeats;
        # append anyway rather than abort practice.
        lesson_words.append(word)

    def _generate_focus_word(
        self,
        alphabet: frozenset[str],
        weighting: LessonWeighting,
        *,
        focus_char: str,
        focus_bigram: Bigram | None,
        focus_bigram_str: str | None,
        focus_pool: tuple[str, ...],
        focus_weighted: WeightedWordlist | None,
        generated_min_len: int = GENERATED_WORD_MIN_LEN,
        generated_max_len: int = GENERATED_WORD_MAX_LEN,
    ) -> str:
        """Word guaranteed to match focus — wordlist pool, then Markov, then inject."""
        if focus_pool:
            wordlist = WeightedWordlist(words=focus_pool, weights=tuple(1.0 for _ in focus_pool))
            if focus_weighted is not None:
                wordlist = focus_weighted
            word = self._generate_word_from_wordlist(
                alphabet,
                weighting,
                wordlist,
                generated_min_len=generated_min_len,
                generated_max_len=generated_max_len,
            )
            if word is not None and word_matches_focus(
                word, focus_char=focus_char, focus_bigram=focus_bigram_str
            ):
                return word
        for _ in range(MAX_RETRIES):
            word = self._generate_word_via_markov(
                alphabet, weighting, generated_min_len, generated_max_len
            )
            if word_matches_focus(word, focus_char=focus_char, focus_bigram=focus_bigram_str):
                return word
        word = self._generate_word_via_markov(
            alphabet, weighting, generated_min_len, generated_max_len
        )
        if focus_bigram is not None:
            prev_char, next_char = chr(focus_bigram.prev_cp), chr(focus_bigram.next_cp)
            return self._inject_focus_bigram(word, prev_char, next_char)
        return self._inject_focus(word, focus_char)

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
        generated_max_len: int,
    ) -> str:
        chars: list[str] = []
        while len(chars) < generated_max_len:
            p_stop = min(1.0, 1.3 ** len(chars) / generated_max_len)
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
