from random import Random

from keystrike.domain.markov import TransitionTable, transition_practice_weight
from keystrike.domain.models import Layout
from keystrike.infrastructure.layout_repo import BUNDLED_LAYOUTS


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
    results = {
        table.sample("", frozenset("bc"), rng, char_weights={"b": 100.0}) for _ in range(20)
    }
    assert results == {"b"}


def test_sample_char_weights_ignores_chars_outside_row():
    table = TransitionTable(order=2, transitions={"a": {"b": 1}})
    rng = Random(1)
    assert table.sample("a", frozenset("ab"), rng, char_weights={"z": 100.0}) == "b"


def test_transition_practice_weight_prefers_different_hand():
    layout = BUNDLED_LAYOUTS["qwerty"]
    assert transition_practice_weight(ord("a"), ord("j"), layout) == 1.5
    assert transition_practice_weight(ord("j"), ord("a"), layout) == 1.5


def test_transition_practice_weight_boosts_different_finger_same_hand():
    layout = BUNDLED_LAYOUTS["qwerty"]
    assert transition_practice_weight(ord("a"), ord("f"), layout) == 1.2


def test_transition_practice_weight_same_finger_is_baseline():
    layout = BUNDLED_LAYOUTS["qwerty"]
    assert transition_practice_weight(ord("a"), ord("q"), layout) == 1.0


def test_transition_practice_weight_missing_key_is_baseline():
    layout = Layout(name="tiny", keys={}, learn_order=())
    assert transition_practice_weight(ord("a"), ord("b"), layout) == 1.0


def test_sample_prefers_different_hand_with_equal_language_weights():
    layout = BUNDLED_LAYOUTS["qwerty"]
    table = TransitionTable(order=2, transitions={"a": {"f": 1, "j": 1}})
    rng = Random(0)
    counts = {"f": 0, "j": 0}
    for _ in range(200):
        ch = table.sample("a", frozenset("afj"), rng, layout=layout)
        assert ch is not None
        counts[ch] += 1
    assert counts["j"] > counts["f"]


def test_sample_transition_weights_bias_weak_pair():
    table = TransitionTable(order=2, transitions={"a": {"b": 1, "c": 1}})
    rng = Random(0)
    counts = {"b": 0, "c": 0}
    for _ in range(200):
        ch = table.sample("a", frozenset("abc"), rng, transition_weights={"ab": 100.0})
        assert ch is not None
        counts[ch] += 1
    assert counts["b"] > counts["c"]
