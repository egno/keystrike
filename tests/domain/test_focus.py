import pytest

from keystrike.domain.enums import FocusKind
from keystrike.domain.focus import FocusReason, select_lesson_focus
from keystrike.domain.models import Bigram, KeyStats, TransitionStats


def _stats(
    codepoint: int,
    mean_time_ns: float,
    error_count: int = 0,
    *,
    last_seen: float = 0.0,
    attempt_count: int | None = None,
) -> KeyStats:
    return KeyStats(
        codepoint=codepoint,
        samples=10,
        mean_time_ns=mean_time_ns,
        error_count=error_count,
        last_seen=last_seen,
        attempt_count=attempt_count if attempt_count is not None else 10 + error_count,
    )


def _transition(
    prev_cp: int,
    next_cp: int,
    mean_time_ns: float,
    *,
    last_seen: float = 0.0,
    error_count: int = 0,
    attempt_count: int | None = None,
) -> TransitionStats:
    attempts = attempt_count if attempt_count is not None else 10 + error_count
    return TransitionStats(
        prev_cp=prev_cp,
        next_cp=next_cp,
        samples=10,
        mean_time_ns=mean_time_ns,
        error_count=error_count,
        last_seen=last_seen,
        attempt_count=attempts,
    )


@pytest.mark.parametrize(
    ("kind", "pair", "message"),
    [
        (FocusKind.TRANSITION_WEAK, None, "requires a pair"),
        (FocusKind.TRANSITION_REVIEW, None, "requires a pair"),
        (FocusKind.KEY_WEAK, Bigram(ord("a"), ord("s")), "must not have a pair"),
    ],
)
def test_focus_reason_rejects_invalid_kind_pair_combo(kind, pair, message):
    with pytest.raises(ValueError, match=message):
        FocusReason(kind=kind, pair=pair)


def test_focus_reason_accepts_transition_with_pair():
    reason = FocusReason(
        kind=FocusKind.TRANSITION_WEAK,
        pair=Bigram(ord("a"), ord("s")),
    )
    assert reason.pair == Bigram(ord("a"), ord("s"))
    assert reason.is_transition is True


def test_focus_reason_key_kind_is_not_transition():
    reason = FocusReason(kind=FocusKind.KEY_WEAK)
    assert reason.is_transition is False


TARGET = 200.0  # ms per char
FAST = 100_000_000.0  # ns: skill >= 1.0
SLOW = 400_000_000.0  # ns: skill 0.5
NOW = 10 * 86_400.0
DAY = 86_400.0
A, S, D = map(ord, "asd")


def _focus(keys, transitions=None, *, freq: dict[Bigram, int] | None = None, **kwargs):
    weights = freq or {}
    return select_lesson_focus(
        (A, S, D),
        keys,
        transitions or {},
        TARGET,
        NOW,
        pair_frequency=lambda pair: weights.get(pair, 1),
        min_attempts=10,
        min_transition_attempts=4,
        **kwargs,
    )


def _cleared_keys():
    return {cp: _stats(cp, FAST, last_seen=NOW) for cp in (A, S, D)}


def _cleared_pairs():
    return {
        Bigram(p, n): _transition(p, n, FAST, last_seen=NOW)
        for p in (A, S, D)
        for n in (A, S, D)
        if p != n
    }


def test_weakest_key_wins_while_any_key_is_not_cleared():
    keys = _cleared_keys()
    keys[S] = _stats(S, SLOW, last_seen=NOW)
    assert _focus(keys) == (S, None)


def test_never_practiced_key_is_not_cleared():
    keys = _cleared_keys()
    del keys[D]
    assert _focus(keys) == (D, None)


def test_last_key_is_kept_while_it_still_needs_work():
    keys = _cleared_keys()
    keys[A] = _stats(A, SLOW, last_seen=NOW)
    keys[S] = _stats(S, 300_000_000.0, last_seen=NOW)
    assert _focus(keys) == (A, None)
    assert _focus(keys, last_key=S) == (S, None)


def test_stalled_last_key_goes_back_to_the_pool():
    keys = _cleared_keys()
    keys[A] = _stats(A, SLOW, last_seen=NOW)
    keys[S] = _stats(S, 300_000_000.0, last_seen=NOW, attempt_count=30)
    assert _focus(keys, last_key=S) == (A, None)


def test_cleared_last_key_is_not_kept():
    keys = _cleared_keys()
    keys[A] = _stats(A, SLOW, last_seen=NOW)
    assert _focus(keys, last_key=S) == (A, None)


def test_gate_pair_wins_over_other_weak_pairs():
    gate = Bigram(S, D)
    transitions = _cleared_pairs()
    transitions[Bigram(A, S)] = _transition(A, S, SLOW, last_seen=NOW)
    assert _focus(_cleared_keys(), transitions, gate=(gate,)) == (D, gate)


def test_weak_pairs_rank_by_weakness_times_language_frequency():
    common, rare = Bigram(A, S), Bigram(S, A)
    transitions = _cleared_pairs()
    del transitions[common]
    del transitions[rare]
    freq = {common: 100, rare: 1}
    assert _focus(_cleared_keys(), transitions, freq=freq) == (S, common)


def test_pair_that_never_occurs_in_the_language_is_skipped():
    never, real = Bigram(A, S), Bigram(S, A)
    transitions = _cleared_pairs()
    del transitions[never]
    transitions[real] = _transition(S, A, SLOW, last_seen=NOW)
    assert _focus(_cleared_keys(), transitions, freq={never: 0}) == (A, real)


def test_last_pair_is_kept_over_a_more_frequent_weak_pair():
    common, last = Bigram(A, S), Bigram(S, D)
    transitions = _cleared_pairs()
    del transitions[common]
    transitions[last] = _transition(S, D, SLOW, last_seen=NOW)
    freq = {common: 100}
    assert _focus(_cleared_keys(), transitions, freq=freq) == (S, common)
    assert _focus(_cleared_keys(), transitions, freq=freq, last_pair=last) == (D, last)


def test_most_overdue_key_or_pair_is_reviewed_when_everything_cleared():
    stale_pair = Bigram(D, A)
    transitions = _cleared_pairs()
    transitions[stale_pair] = _transition(D, A, FAST, last_seen=NOW - 3 * DAY)
    keys = _cleared_keys()
    keys[S] = _stats(S, FAST, last_seen=NOW - 2 * DAY)
    assert _focus(keys, transitions) == (A, stale_pair)
    keys[S] = _stats(S, FAST, last_seen=NOW - 5 * DAY)  # ties the pair: keys first
    assert _focus(keys, transitions) == (S, None)


def test_first_unlocked_key_when_nothing_needs_work():
    assert _focus(_cleared_keys(), _cleared_pairs()) == (A, None)
