"""Parse and filter user-imported word lists for lesson generation."""

from __future__ import annotations

from .word_bounds import MAX_WORD_LEN, MIN_WORD_LEN


def parse_wordlist_text(text: str) -> list[str]:
    """Lowercase alphabetic words only — matches build_markov corpus filter."""
    return [w for w in text.splitlines() if w.isalpha() and w.islower()]


def words_for_alphabet(words: list[str], alphabet: frozenset[str]) -> list[str]:
    return [
        w
        for w in words
        if MIN_WORD_LEN <= len(w) <= MAX_WORD_LEN and set(w) <= alphabet
    ]
