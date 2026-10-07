from keystrike.domain.alphabet_cut import add_alphabet_cut, closed_keys, forget_closed_keys
from keystrike.domain.models import AlphabetCut, Bigram, KeyTally, SessionStats

_ORDER = (1, 2, 3, 4, 5)
_TALLY = KeyTally(samples=10, time_ns=1_000_000_000, errors=0, attempts=10)


def test_add_alphabet_cut_drops_cuts_it_covers():
    cuts = (AlphabetCut(at=10.0, size=3), AlphabetCut(at=20.0, size=6))
    assert add_alphabet_cut(cuts, AlphabetCut(at=30.0, size=4)) == (
        AlphabetCut(at=10.0, size=3),
        AlphabetCut(at=30.0, size=4),
    )


def test_closed_keys_uses_smallest_size_among_later_cuts():
    cuts = (AlphabetCut(at=10.0, size=2), AlphabetCut(at=20.0, size=4))
    assert closed_keys(5.0, _ORDER, cuts) == {3, 4, 5}
    assert closed_keys(15.0, _ORDER, cuts) == {5}
    assert closed_keys(25.0, _ORDER, cuts) == frozenset()


def test_forget_closed_keys_drops_keys_and_their_bigrams():
    stats = SessionStats(
        keys={cp: _TALLY for cp in _ORDER},
        transitions={Bigram(1, 2): _TALLY, Bigram(2, 4): _TALLY, Bigram(5, 1): _TALLY},
    )
    forgotten = forget_closed_keys(stats, 5.0, _ORDER, (AlphabetCut(at=10.0, size=3),))
    assert set(forgotten.keys) == {1, 2, 3}
    assert set(forgotten.transitions) == {Bigram(1, 2)}


def test_forget_closed_keys_keeps_sessions_after_the_cut():
    stats = SessionStats(keys={cp: _TALLY for cp in _ORDER})
    assert forget_closed_keys(stats, 20.0, _ORDER, (AlphabetCut(at=10.0, size=3),)) is stats
