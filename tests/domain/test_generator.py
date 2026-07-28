from random import Random

from keystrike.domain.generator import (
    MAX_WORD_LEN,
    MIN_WORD_LEN,
    AdaptiveGenerator,
)
from keystrike.domain.markov import TransitionTable


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
