"""Word length bounds for dictionary word-list filtering (not Markov generation)."""

MIN_WORD_LEN = 3
MAX_WORD_LEN = 10


def effective_wordlist_bounds(
    min_len: int = MIN_WORD_LEN,
    max_len: int = MAX_WORD_LEN,
) -> tuple[int, int]:
    """Clamp dictionary bounds; ensure min <= max and both are at least 1."""
    min_len = max(1, min_len)
    max_len = max(1, max_len)
    min_len = min(min_len, max_len)
    return min_len, max_len
