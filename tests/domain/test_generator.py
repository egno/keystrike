from random import Random

from keystrike.domain.generator import (
    AdaptiveGenerator,
    cpm_from_wpm,
    typical_chars_per_word,
    wpm_from_cpm,
)
from keystrike.domain.markov import TransitionTable
from keystrike.domain.word_bounds import MAX_WORD_LEN, MIN_WORD_LEN


def _uniform_table(alphabet: str) -> TransitionTable:
    row = {ch: 1 for ch in alphabet}
    return TransitionTable(order=2, transitions={"": row})


def test_generate_word_length_within_bounds():
    generator = AdaptiveGenerator(table=_uniform_table("abc"), rng=Random(0))
    for _ in range(20):
        word = generator.generate_word(frozenset("abc"))
        assert MIN_WORD_LEN <= len(word) <= MAX_WORD_LEN


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
        frozenset("ab"), focus_char="a", word_count=20, char_weights={"a": 50.0},
    )
    assert lesson.count("a") > lesson.count("b")


def test_generate_word_uses_wordlist_when_provided():
    generator = AdaptiveGenerator(table=_uniform_table("xyz"), rng=Random(0))
    words = ["cab", "bad", "dab"]
    for _ in range(10):
        word = generator.generate_word(frozenset("abcd"), words=words)
        assert word in words


def test_generate_word_falls_back_to_markov_without_wordlist():
    generator = AdaptiveGenerator(table=_uniform_table("abc"), rng=Random(0))
    word = generator.generate_word(frozenset("abc"))
    assert set(word) <= {"a", "b", "c"}


def test_generate_word_falls_back_when_wordlist_outside_alphabet():
    generator = AdaptiveGenerator(table=_uniform_table("abc"), rng=Random(0))
    word = generator.generate_word(frozenset("abc"), words=["xyz", "qrs"])
    assert set(word) <= {"a", "b", "c"}


def test_generate_wordlist_char_weights_bias():
    generator = AdaptiveGenerator(table=_uniform_table("ab"), rng=Random(0))
    words = ["aaa", "bbb"]
    counts = {"a": 0, "b": 0}
    for _ in range(50):
        word = generator.generate_word(
            frozenset("ab"), char_weights={"a": 100.0, "b": 1.0}, words=words,
        )
        counts[word[0]] += 1
    assert counts["a"] > counts["b"]


def test_generate_lesson_focus_wordlist_overweights_focus_char():
    generator = AdaptiveGenerator(table=_uniform_table("ab"), rng=Random(0))
    words = ["aaa", "bbb"]
    focus_counts = 0
    for seed in range(40):
        generator.rng = Random(seed)
        lesson = generator.generate_lesson(
            frozenset("ab"),
            focus_char="a",
            word_count=8,
            char_weights={"a": 1.75, "b": 1.0},
            words=words,
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
            char_weights={"a": 5.25, "b": 1.0},
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
            focus_bigram=(ord("a"), ord("z")),
        )
        assert "az" in lesson.replace(" ", "")


def test_wpm_cpm_conversion_uses_typical_word_length():
    avg = typical_chars_per_word()
    assert cpm_from_wpm(80) == round(80 * avg)
    assert wpm_from_cpm(round(80 * avg)) == 80
