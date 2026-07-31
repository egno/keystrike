from random import Random
from unittest.mock import patch

from keystrike.domain.generator import (
    FOCUS_WORD_MIN_FRACTION,
    AdaptiveGenerator,
    LessonWeighting,
    clamp_focus_word_fraction,
    cpm_from_wpm,
    effective_generated_word_bounds,
    min_focus_words,
    typical_chars_per_word,
    weak_focus_word_quota,
    word_matches_focus,
    wordlist_weight_for_word,
    wpm_from_cpm,
)
from keystrike.domain.markov import TransitionTable
from keystrike.domain.models import GENERATED_WORD_MAX_LEN, GENERATED_WORD_MIN_LEN, Bigram


def _uniform_table(alphabet: str) -> TransitionTable:
    row = {ch: 1 for ch in alphabet}
    return TransitionTable(order=2, transitions={"": row})


def test_generate_word_length_within_bounds():
    generator = AdaptiveGenerator(table=_uniform_table("abc"), rng=Random(0))
    for _ in range(20):
        word = generator.generate_word(frozenset("abc"))
        assert GENERATED_WORD_MIN_LEN <= len(word) <= GENERATED_WORD_MAX_LEN


def test_generate_markov_word_respects_custom_generated_bounds():
    generator = AdaptiveGenerator(table=_uniform_table("abc"), rng=Random(0))
    for seed in range(30):
        generator.rng = Random(seed)
        word = generator.generate_word(
            frozenset("abc"),
            generated_min_len=2,
            generated_max_len=4,
        )
        assert 2 <= len(word) <= 4


def test_effective_generated_word_bounds_clamps_invalid():
    assert effective_generated_word_bounds(0, 10) == (1, 10)
    assert effective_generated_word_bounds(5, 0) == (1, 1)
    assert effective_generated_word_bounds(8, 4) == (4, 4)


def test_generate_lesson_markov_respects_custom_generated_bounds():
    generator = AdaptiveGenerator(table=_uniform_table("abc"), rng=Random(0))
    for seed in range(20):
        generator.rng = Random(seed)
        lesson = generator.generate_lesson(
            frozenset("abc"),
            focus_char="a",
            word_count=8,
            generated_min_len=2,
            generated_max_len=4,
        )
        for word in lesson.split():
            assert 2 <= len(word) <= 4, f"seed={seed}: {word!r}"


def test_generate_word_only_uses_alphabet_chars():
    generator = AdaptiveGenerator(table=_uniform_table("abc"), rng=Random(0))
    word = generator.generate_word(frozenset("abc"))
    assert set(word) <= {"a", "b", "c"}


def test_generate_lesson_word_count():
    generator = AdaptiveGenerator(table=_uniform_table("abc"), rng=Random(0))
    lesson = generator.generate_lesson(frozenset("abc"), focus_char="a", word_count=5)
    assert len(lesson.split(" ")) == 5


def test_generate_lesson_always_includes_focus_char():
    # Alphabet excludes "z" entirely from the table, so it can only appear via injection.
    generator = AdaptiveGenerator(table=_uniform_table("abc"), rng=Random(0))
    for seed in range(10):
        generator.rng = Random(seed)
        lesson = generator.generate_lesson(frozenset("abcz"), focus_char="z", word_count=4)
        assert "z" in lesson


def test_generate_lesson_char_weights_bias_toward_weak_key():
    generator = AdaptiveGenerator(table=_uniform_table("ab"), rng=Random(0))
    lesson = generator.generate_lesson(
        frozenset("ab"),
        focus_char="a",
        word_count=20,
        weighting=LessonWeighting(char_weights={"a": 50.0}),
    )
    assert lesson.count("a") > lesson.count("b")


def test_generate_word_uses_wordlist_when_provided():
    generator = AdaptiveGenerator(table=_uniform_table("xyz"), rng=Random(0))
    words = ("cab", "bad", "dab")
    for _ in range(10):
        word = generator.generate_word(frozenset("abcd"), LessonWeighting(words=words))
        assert word in words


def test_wordlist_respects_generated_bounds():
    """Dictionary sampling honors generated_word_min/max, not dictionary 3-10."""
    generator = AdaptiveGenerator(table=_uniform_table("abc"), rng=Random(0))
    words = ("abc", "abcd", "abcde", "abcdef", "abcdefg", "abcdefgh", "abcdefghi", "abcdefghij")
    for _ in range(20):
        word = generator.generate_word(
            frozenset("abcdefghij"),
            LessonWeighting(words=words),
            generated_min_len=2,
            generated_max_len=4,
        )
        assert 2 <= len(word) <= 4
        if word in words:
            assert len(word) <= 4


def test_generate_word_falls_back_to_markov_without_wordlist():
    generator = AdaptiveGenerator(table=_uniform_table("abc"), rng=Random(0))
    word = generator.generate_word(frozenset("abc"))
    assert set(word) <= {"a", "b", "c"}


def test_generate_word_falls_back_when_wordlist_outside_alphabet():
    generator = AdaptiveGenerator(table=_uniform_table("abc"), rng=Random(0))
    word = generator.generate_word(
        frozenset("abc"),
        LessonWeighting(words=("xyz", "qrs")),
    )
    assert set(word) <= {"a", "b", "c"}


def test_generate_wordlist_char_weights_bias():
    generator = AdaptiveGenerator(table=_uniform_table("ab"), rng=Random(0))
    words = ("aaa", "bbb")
    counts = {"a": 0, "b": 0}
    for _ in range(50):
        word = generator.generate_word(
            frozenset("ab"),
            LessonWeighting(char_weights={"a": 100.0, "b": 1.0}, words=words),
        )
        counts[word[0]] += 1
    assert counts["a"] > counts["b"]


def test_generate_wordlist_transition_weights_bias():
    generator = AdaptiveGenerator(table=_uniform_table("abcd"), rng=Random(0))
    words = ("cab", "cad")
    counts = {"cab": 0, "cad": 0}
    for _ in range(50):
        word = generator.generate_word(
            frozenset("abcd"),
            LessonWeighting(
                transition_weights={
                    Bigram(ord("a"), ord("b")): 100.0,
                    Bigram(ord("a"), ord("d")): 1.0,
                },
                words=words,
            ),
        )
        counts[word] += 1
    assert counts["cab"] > counts["cad"]


def test_wordlist_weight_for_word_combines_char_and_transition_weights():
    weight = wordlist_weight_for_word(
        "cab",
        weighting=LessonWeighting(
            char_weights={"a": 2.0, "b": 2.0, "c": 1.0},
            transition_weights={Bigram(ord("a"), ord("b")): 3.0, Bigram(ord("b"), ord("c")): 1.0},
        ),
    )
    assert weight == (2.0 + 2.0 + 1.0) * (3.0 + 1.0)


def test_generate_lesson_wordlist_transition_weights_bias():
    generator = AdaptiveGenerator(table=_uniform_table("as"), rng=Random(0))
    words = ("asa", "ass", "sas", "ssa")
    ssa_count = 0
    for seed in range(50):
        generator.rng = Random(seed)
        lesson = generator.generate_lesson(
            frozenset("as"),
            focus_char="s",
            word_count=12,
            max_word_repeats=12,
            weighting=LessonWeighting(
                transition_weights={
                    Bigram(ord("a"), ord("s")): 100.0,
                    Bigram(ord("s"), ord("a")): 1.0,
                    Bigram(ord("s"), ord("s")): 1.0,
                },
                words=words,
            ),
        )
        ssa_count += lesson.split().count("ssa")
    assert ssa_count < 80  # uniform would land near ~150 of 600 picks


def test_generate_lesson_focus_wordlist_overweights_focus_char():
    generator = AdaptiveGenerator(table=_uniform_table("ab"), rng=Random(0))
    words = ("aaa", "bbb")
    focus_counts = 0
    for seed in range(40):
        generator.rng = Random(seed)
        lesson = generator.generate_lesson(
            frozenset("ab"),
            focus_char="a",
            word_count=8,
            weighting=LessonWeighting(char_weights={"a": 1.75, "b": 1.0}, words=words),
        )
        if lesson.count("a") > lesson.count("b"):
            focus_counts += 1
    assert focus_counts >= 35


def test_generate_lesson_markov_overweights_focus_char():
    generator = AdaptiveGenerator(table=_uniform_table("ab"), rng=Random(0))
    focus_counts = 0
    for seed in range(40):
        generator.rng = Random(seed)
        lesson = generator.generate_lesson(
            frozenset("ab"),
            focus_char="a",
            word_count=12,
            weighting=LessonWeighting(char_weights={"a": 5.25, "b": 1.0}),
        )
        if lesson.count("a") > lesson.count("b"):
            focus_counts += 1
    assert focus_counts >= 30


def test_generate_lesson_injects_focus_bigram():
    generator = AdaptiveGenerator(table=_uniform_table("abc"), rng=Random(0))
    for seed in range(10):
        generator.rng = Random(seed)
        lesson = generator.generate_lesson(
            frozenset("abc"),
            focus_char="c",
            word_count=4,
            focus_bigram=Bigram(ord("a"), ord("z")),
        )
        assert "az" in lesson.replace(" ", "")


def test_wpm_cpm_conversion_uses_typical_word_length():
    avg = typical_chars_per_word()
    assert cpm_from_wpm(80) == round(80 * avg)
    assert wpm_from_cpm(round(80 * avg)) == 80


def test_wpm_cpm_conversion_uses_custom_generated_bounds():
    avg = typical_chars_per_word(generated_min_len=2, generated_max_len=4)
    assert avg == 3.0
    assert cpm_from_wpm(80, generated_min_len=2, generated_max_len=4) == 240
    assert wpm_from_cpm(240, generated_min_len=2, generated_max_len=4) == 80


def test_markov_fallback_pads_to_generated_min_len():
    generator = AdaptiveGenerator(table=_uniform_table("ab"), rng=Random(0))
    with patch.object(
        AdaptiveGenerator,
        "_sample_word",
        autospec=True,
        return_value="ab",
    ):
        word = generator.generate_word(frozenset("ab"), generated_min_len=5, generated_max_len=8)
    assert 5 <= len(word) <= 8
    assert set(word) <= {"a", "b"}


def test_min_focus_words_uses_ceiling():
    assert min_focus_words(12, FOCUS_WORD_MIN_FRACTION) == 8
    assert min_focus_words(5, FOCUS_WORD_MIN_FRACTION) == 3


def test_clamp_focus_word_fraction_bounds():
    assert clamp_focus_word_fraction(1.5) == 1.0
    assert clamp_focus_word_fraction(-0.1) == 0.0


def test_weak_focus_word_quota_clamps_invalid_fraction():
    assert weak_focus_word_quota(12, 1.5) == 12
    assert weak_focus_word_quota(12, -0.1) == 0


def test_word_matches_focus_char_and_bigram():
    assert word_matches_focus("cab", focus_char="a", focus_bigram=None)
    assert not word_matches_focus("bbb", focus_char="a", focus_bigram=None)
    assert word_matches_focus("cab", focus_char="x", focus_bigram="ab")
    assert not word_matches_focus("bbb", focus_char="x", focus_bigram="ab")


def test_generate_lesson_weak_guarantees_focus_word_fraction():
    generator = AdaptiveGenerator(table=_uniform_table("ab"), rng=Random(0))
    quota = min_focus_words(12, FOCUS_WORD_MIN_FRACTION)
    for seed in range(50):
        generator.rng = Random(seed)
        lesson = generator.generate_lesson(
            frozenset("ab"),
            focus_char="a",
            word_count=12,
            min_focus_words=quota,
            weighting=LessonWeighting(char_weights={"a": 1.75, "b": 1.0}),
        )
        words = lesson.split()
        focus_words = sum(
            1 for w in words if word_matches_focus(w, focus_char="a", focus_bigram=None)
        )
        assert focus_words >= quota, f"seed={seed}: {focus_words}/{len(words)} focus words"


def test_focus_quota_falls_back_to_markov_when_wordlist_sparse():
    """Tiny wordlist with one focus word — quota still met via Markov/inject."""
    generator = AdaptiveGenerator(table=_uniform_table("ab"), rng=Random(0))
    words = ("aaa", "bbb", "bbb")  # only one focus word in pool
    quota = min_focus_words(12, FOCUS_WORD_MIN_FRACTION)
    for seed in range(20):
        generator.rng = Random(seed)
        lesson = generator.generate_lesson(
            frozenset("ab"),
            focus_char="a",
            word_count=12,
            min_focus_words=quota,
            weighting=LessonWeighting(words=words, char_weights={"a": 2.0, "b": 1.0}),
        )
        focus_words = sum(
            1 for w in lesson.split() if word_matches_focus(w, focus_char="a", focus_bigram=None)
        )
        assert focus_words >= quota, f"seed={seed}: {focus_words} focus words"


def test_generate_lesson_strong_focus_keeps_minimum_one():
    """min_focus_words=1 — probabilistic bias, not 60% quota."""
    # "z" is outside the Markov table; it only appears via injection.
    generator = AdaptiveGenerator(table=_uniform_table("ab"), rng=Random(0))
    below_quota_seeds = 0
    for seed in range(50):
        generator.rng = Random(seed)
        lesson = generator.generate_lesson(
            frozenset("abz"),
            focus_char="z",
            word_count=12,
            min_focus_words=1,
        )
        words = lesson.split()
        focus_words = sum(
            1 for w in words if word_matches_focus(w, focus_char="z", focus_bigram=None)
        )
        assert focus_words >= 1
        if focus_words < min_focus_words(12, FOCUS_WORD_MIN_FRACTION):
            below_quota_seeds += 1
    assert below_quota_seeds > 0  # not all seeds hit 60% quota


def test_focus_quota_samples_without_replacement():
    """Focus pool words appear at most once when pool size >= quota."""
    generator = AdaptiveGenerator(table=_uniform_table("abcdefgh"), rng=Random(0))
    words = ("toe", "doe", "foe", "hoe")
    for seed in range(50):
        generator.rng = Random(seed)
        lesson = generator.generate_lesson(
            frozenset("abcdefgho"),
            focus_char="o",
            word_count=4,
            min_focus_words=4,
            weighting=LessonWeighting(words=words),
        )
        split = lesson.split()
        for w in words:
            assert split.count(w) <= 1, f"seed={seed}: {w} repeated in {split}"


def test_focus_quota_markov_fills_when_pool_smaller_than_quota():
    """Tiny focus pool — without-replacement draw then Markov fills quota."""
    alphabet = frozenset("arstneio")
    generator = AdaptiveGenerator(table=_uniform_table("arstneio"), rng=Random(0))
    words = ("toe", "toes", "are", "not", "sea", "rat")
    quota = 8
    for seed in range(50):
        generator.rng = Random(seed)
        lesson = generator.generate_lesson(
            alphabet,
            focus_char="e",
            word_count=12,
            min_focus_words=quota,
            focus_bigram=Bigram(ord("o"), ord("e")),
            weighting=LessonWeighting(
                words=words,
                transition_weights={Bigram(ord("o"), ord("e")): 50.0},
            ),
        )
        split = lesson.split()
        focus_words = sum(
            1 for w in split if word_matches_focus(w, focus_char="e", focus_bigram="oe")
        )
        assert focus_words >= quota, f"seed={seed}: {focus_words}/{quota} focus words"
        assert max(split.count(w) for w in set(split)) <= 2, f"seed={seed}: repeat cap broken"
        assert len(set(split)) > 2, f"seed={seed}: lesson too repetitive: {split}"


def test_lesson_caps_word_repeats():
    """No word appears more than twice in a lesson (focus + general slots)."""
    generator = AdaptiveGenerator(table=_uniform_table("ab"), rng=Random(0))
    words = ("aaa", "bbb", "aba", "bab")
    quota = min_focus_words(12, FOCUS_WORD_MIN_FRACTION)
    for seed in range(50):
        generator.rng = Random(seed)
        lesson = generator.generate_lesson(
            frozenset("ab"),
            focus_char="a",
            word_count=12,
            min_focus_words=quota,
            weighting=LessonWeighting(char_weights={"a": 5.0, "b": 1.0}, words=words),
        )
        split = lesson.split()
        for w in set(split):
            assert split.count(w) <= 2, f"seed={seed}: {w} appears {split.count(w)} times"


def test_lesson_caps_word_repeats_on_strong_focus_path():
    """Repeat cap applies when min_focus_words=1 (confident focus)."""
    generator = AdaptiveGenerator(table=_uniform_table("ab"), rng=Random(0))
    words = ("aaa", "bbb")
    for seed in range(20):
        generator.rng = Random(seed)
        lesson = generator.generate_lesson(
            frozenset("ab"),
            focus_char="a",
            word_count=8,
            min_focus_words=1,
            weighting=LessonWeighting(words=words),
        )
        split = lesson.split()
        assert max(split.count(w) for w in set(split)) <= 2, f"seed={seed}: {split}"


def test_generate_lesson_clamps_max_word_repeats_zero():
    """max_word_repeats=0 would reject every word; clamp to 1 instead of crashing."""
    generator = AdaptiveGenerator(table=_uniform_table("ab"), rng=Random(0))
    lesson = generator.generate_lesson(
        frozenset("ab"),
        focus_char="a",
        word_count=6,
        min_focus_words=min_focus_words(6, FOCUS_WORD_MIN_FRACTION),
        max_word_repeats=0,
        weighting=LessonWeighting(char_weights={"a": 3.0, "b": 1.0}),
    )
    assert len(lesson.split()) == 6


def test_generate_lesson_survives_small_alphabet_repeat_cap():
    """One-letter alphabet has few distinct words; must not crash when cap is tight."""
    generator = AdaptiveGenerator(table=_uniform_table("a"), rng=Random(0))
    lesson = generator.generate_lesson(
        frozenset("a"),
        focus_char="a",
        word_count=12,
        min_focus_words=1,
        max_word_repeats=1,
    )
    assert len(lesson.split()) == 12


def test_generate_lesson_clamps_zero_word_count():
    generator = AdaptiveGenerator(table=_uniform_table("ab"), rng=Random(0))
    lesson = generator.generate_lesson(
        frozenset("ab"),
        focus_char="a",
        word_count=0,
        min_focus_words=1,
    )
    assert len(lesson.split()) == 1


def test_generate_lesson_weak_guarantees_focus_bigram_fraction():
    generator = AdaptiveGenerator(table=_uniform_table("abc"), rng=Random(0))
    bigram = Bigram(ord("a"), ord("b"))
    bigram_str = bigram.chars()
    quota = min_focus_words(12, FOCUS_WORD_MIN_FRACTION)
    for seed in range(50):
        generator.rng = Random(seed)
        lesson = generator.generate_lesson(
            frozenset("abc"),
            focus_char="b",
            word_count=12,
            min_focus_words=quota,
            focus_bigram=bigram,
            weighting=LessonWeighting(
                transition_weights={bigram: 50.0},
                words=("cab", "abc", "bab", "bbb", "ccc"),
            ),
        )
        words = lesson.split()
        focus_words = sum(
            1 for w in words if word_matches_focus(w, focus_char="b", focus_bigram=bigram_str)
        )
        assert focus_words >= quota, f"seed={seed}: {focus_words}/{len(words)} bigram words"
