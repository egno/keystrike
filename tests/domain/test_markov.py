from random import Random

from keystrike.domain.markov import TransitionTable


def test_sample_picks_from_exact_context():
    table = TransitionTable(order=2, transitions={"ab": {"c": 100, "z": 0}})
    rng = Random(1)
    assert table.sample("ab", frozenset("abcz"), rng) == "c"


def test_sample_falls_back_to_shorter_context():
    table = TransitionTable(order=2, transitions={"b": {"c": 1}})
    rng = Random(1)
    # "xb" has no exact row, but its 1-char suffix "b" does.
    assert table.sample("xb", frozenset("bcxz"), rng) == "c"


def test_sample_falls_back_to_global_distribution():
    table = TransitionTable(order=2, transitions={"": {"e": 1}})
    rng = Random(1)
    assert table.sample("zz", frozenset("ez"), rng) == "e"


def test_sample_filters_to_alphabet():
    table = TransitionTable(order=2, transitions={"a": {"b": 1, "c": 100}})
    rng = Random(1)
    # "c" is excluded from the alphabet, so only "b" can ever be picked.
    for _ in range(10):
        assert table.sample("a", frozenset("ab"), rng) == "b"


def test_sample_returns_none_when_nothing_matches():
    table = TransitionTable(order=2, transitions={"a": {"b": 1}})
    rng = Random(1)
    assert table.sample("a", frozenset("xyz"), rng) is None


def test_sample_char_weights_bias_toward_weighted_char():
    table = TransitionTable(order=2, transitions={"": {"b": 1, "c": 1}})
    rng = Random(1)
    # "b" would be a coin flip against "c" on raw weight alone; a large
    # char_weights bias should make it win consistently.
    results = {table.sample("", frozenset("bc"), rng, {"b": 100.0}) for _ in range(20)}
    assert results == {"b"}


def test_sample_char_weights_ignores_chars_outside_row():
    table = TransitionTable(order=2, transitions={"a": {"b": 1}})
    rng = Random(1)
    assert table.sample("a", frozenset("ab"), rng, {"z": 100.0}) == "b"
