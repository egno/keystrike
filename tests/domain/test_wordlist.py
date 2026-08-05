from pathlib import Path

from keystrike.domain.word_bounds import MAX_WORD_LEN, MIN_WORD_LEN, effective_wordlist_bounds
from keystrike.domain.wordlist import parse_wordlist_text, words_for_alphabet


def test_parse_wordlist_text_lowercase_alpha_only():
    text = "hello\nWorld\n123\nfoo-bar\ntest\n"
    assert parse_wordlist_text(text) == ["hello", "test"]


def test_parse_wordlist_text_matches_fixture():
    raw = (Path(__file__).parent.parent / "fixtures" / "wordlist_sample.txt").read_text()
    words = parse_wordlist_text(raw)
    assert "the" in words
    assert "ONE" not in words
    assert "a1b" not in words


def test_effective_wordlist_bounds_clamps_invalid():
    assert effective_wordlist_bounds() == (MIN_WORD_LEN, MAX_WORD_LEN)
    assert effective_wordlist_bounds(0, 10) == (1, 10)
    assert effective_wordlist_bounds(5, 0) == (1, 1)


def test_words_for_alphabet_filters_length_and_chars():
    words = ["ab", "abc", "abcd", "xyz", "cat", "dog"]
    alphabet = frozenset("abcd")
    filtered = words_for_alphabet(words, alphabet)
    assert "abc" in filtered
    assert "abcd" in filtered
    assert "ab" not in filtered  # too short
    assert "xyz" not in filtered  # outside alphabet
    assert all(MIN_WORD_LEN <= len(w) <= MAX_WORD_LEN for w in filtered)
