from keystrike.domain.confidence import confidence_of, skill_of
from keystrike.domain.models import Bigram, KeyStats, TransitionStats
from keystrike.domain.newest_key import newest_key_gating_cohort
from keystrike.domain.unlock import (
    compute_unlocked,
    newest_key_clears_transition_gate,
    newest_key_transition_gate_progress,
)


def _stats(
    codepoint: int,
    mean_time_ns: float,
    error_count: int = 0,
    *,
    last_seen: float = 0.0,
) -> KeyStats:
    return KeyStats(
        codepoint=codepoint,
        samples=10,
        mean_time_ns=mean_time_ns,
        error_count=error_count,
        last_seen=last_seen,
        attempt_count=10 + error_count,
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


def test_compute_unlocked_stalls_when_calibrating_on_attempts():
    learn_order = (1, 2, 3)
    stats = {
        1: _stats(1, mean_time_ns=100_000_000.0),
        2: KeyStats(
            2,
            samples=9,
            mean_time_ns=100_000_000.0,
            error_count=0,
            last_seen=0.0,
            attempt_count=9,
        ),
    }
    target = 200.0
    assert skill_of(2, stats, target=target) == 1.0
    assert confidence_of(2, stats, target=target) == 0.9
    unlocked = compute_unlocked(learn_order, alphabet_size=2, stats=stats, target=target)
    assert unlocked == (1, 2)


def test_compute_unlocked_advances_when_skill_and_attempts_met():
    learn_order = (1, 2, 3)
    stats = {
        1: _stats(1, mean_time_ns=100_000_000.0),
        2: _stats(2, mean_time_ns=100_000_000.0),
    }
    unlocked = compute_unlocked(learn_order, alphabet_size=2, stats=stats, target=200.0)
    assert unlocked == (1, 2, 3)


def test_compute_unlocked_stalls_when_sparse_key_looks_fast():
    learn_order = (1, 2, 3)
    stats = {
        1: _stats(1, mean_time_ns=100_000_000.0),
        2: KeyStats(
            2,
            samples=1,
            mean_time_ns=100_000_000.0,
            error_count=1,
            last_seen=0.0,
            attempt_count=2,
        ),
    }
    unlocked = compute_unlocked(learn_order, alphabet_size=2, stats=stats, target=200.0)
    assert unlocked == (1, 2)


def test_compute_unlocked_stalls_on_high_error_rate_despite_fast_speed():
    learn_order = (1, 2, 3, 4)
    # speed 2.0, but only 50% accuracy -> min(2.0, 0.5) = 0.5 < threshold
    stats = {1: _stats(1, mean_time_ns=100_000_000.0, error_count=10)}
    unlocked = compute_unlocked(
        learn_order, alphabet_size=1, stats=stats, target=200.0, threshold=1.5
    )
    assert unlocked == (1,)


def test_compute_unlocked_force_includes_alphabet_size():
    learn_order = tuple(range(10))
    unlocked = compute_unlocked(learn_order, alphabet_size=3, stats={}, target=200.0)
    assert unlocked == learn_order[:3]


def test_compute_unlocked_caps_alphabet_size_at_learn_order_length():
    learn_order = tuple(range(4))
    unlocked = compute_unlocked(learn_order, alphabet_size=99, stats={}, target=200.0)
    assert unlocked == learn_order


def test_compute_unlocked_advances_when_threshold_met():
    learn_order = (1, 2, 3, 4)
    stats = {1: _stats(1, mean_time_ns=100_000_000.0)}  # confidence 2.0
    unlocked = compute_unlocked(learn_order, alphabet_size=1, stats=stats, target=200.0)
    assert unlocked == (1, 2)


def test_compute_unlocked_stalls_when_threshold_not_met():
    learn_order = (1, 2, 3, 4)
    stats = {1: _stats(1, mean_time_ns=400_000_000.0)}  # confidence 0.5
    unlocked = compute_unlocked(learn_order, alphabet_size=1, stats=stats, target=200.0)
    assert unlocked == (1,)


def test_compute_unlocked_ignores_weak_transitions():
    learn_order = tuple(ord(c) for c in "eabcdfghm")
    stats = {cp: _stats(cp, mean_time_ns=100_000_000.0) for cp in learn_order[:8]}
    unlocked = compute_unlocked(
        learn_order,
        alphabet_size=8,
        stats=stats,
        target=200.0,
    )
    assert unlocked == learn_order[:9]
    assert unlocked[-1] == ord("m")


def test_compute_unlocked_gate_blocks_next_key_on_weak_newest_bigram():
    """With a transitions gate, the newest key's weakest bigram must clear
    before the next key opens -- unlike the transitions-agnostic default."""
    e, a, b = ord("e"), ord("a"), ord("b")
    learn_order = (e, a, b)
    now = 1_700_000_000.0
    stats = {
        e: _stats(e, mean_time_ns=100_000_000.0, last_seen=now),
        a: _stats(a, mean_time_ns=100_000_000.0, last_seen=now),
    }
    transitions = {
        Bigram(e, a): _transition(e, a, 400_000_000.0, last_seen=now, attempt_count=4),
        Bigram(a, e): _transition(a, e, 100_000_000.0, last_seen=now, attempt_count=4),
    }
    unlocked = compute_unlocked(
        learn_order,
        alphabet_size=2,
        stats=stats,
        target=200.0,
        transitions=transitions,
    )
    assert unlocked == (e, a)


def test_compute_unlocked_gate_allows_next_key_once_newest_bigram_clears():
    e, a, b = ord("e"), ord("a"), ord("b")
    learn_order = (e, a, b)
    now = 1_700_000_000.0
    stats = {
        e: _stats(e, mean_time_ns=100_000_000.0, last_seen=now),
        a: _stats(a, mean_time_ns=100_000_000.0, last_seen=now),
    }
    transitions = {
        Bigram(e, a): _transition(e, a, 100_000_000.0, last_seen=now, attempt_count=4),
        Bigram(a, e): _transition(a, e, 100_000_000.0, last_seen=now, attempt_count=4),
    }
    unlocked = compute_unlocked(
        learn_order,
        alphabet_size=2,
        stats=stats,
        target=200.0,
        transitions=transitions,
    )
    assert unlocked == (e, a, b)


def test_compute_unlocked_gate_stall_cap_unblocks_stuck_bigram():
    """A bigram that never clears threshold shouldn't block progression
    forever once it's been drilled past the stall cap."""
    e, a, b = ord("e"), ord("a"), ord("b")
    learn_order = (e, a, b)
    now = 1_700_000_000.0
    stats = {
        e: _stats(e, mean_time_ns=100_000_000.0, last_seen=now),
        a: _stats(a, mean_time_ns=100_000_000.0, last_seen=now),
    }
    transitions = {
        Bigram(e, a): _transition(e, a, 400_000_000.0, last_seen=now, attempt_count=12),
        Bigram(a, e): _transition(a, e, 100_000_000.0, last_seen=now, attempt_count=12),
    }
    unlocked = compute_unlocked(
        learn_order,
        alphabet_size=2,
        stats=stats,
        target=200.0,
        transitions=transitions,
        transition_stall_attempts_cap=12,
    )
    assert unlocked == (e, a, b)


def test_configured_cohort_limit_changes_unlock_gate():
    a, b, c, d = map(ord, "abcd")
    unlocked = (a, b, c)
    stats = {cp: _stats(cp, mean_time_ns=100_000_000.0) for cp in unlocked}
    transitions = {
        pair: _transition(*pair, 100_000_000.0, attempt_count=4)
        for pair in newest_key_gating_cohort(unlocked, stats, limit=2)
    }
    assert compute_unlocked(
        (a, b, c, d),
        3,
        stats,
        200.0,
        transitions=transitions,
        gating_bigram_limit=2,
    ) == (a, b, c, d)
    assert (
        compute_unlocked(
            (a, b, c, d),
            3,
            stats,
            200.0,
            transitions=transitions,
            gating_bigram_limit=4,
        )
        == unlocked
    )


def test_gate_progress_releases_each_stalled_cohort_member():
    a, b = map(ord, "ab")
    stats = {
        a: _stats(a, mean_time_ns=100_000_000.0),
        b: _stats(b, mean_time_ns=100_000_000.0),
    }
    transitions = {
        pair: _transition(*pair, 400_000_000.0, attempt_count=12)
        for pair in newest_key_gating_cohort((a, b), stats)
    }
    assert newest_key_transition_gate_progress(
        (a, b),
        transitions,
        200.0,
        stats,
        stall_attempts_cap=12,
    ) == (2, 2)


def test_newest_key_clears_transition_gate_vacuous_with_one_key():
    now = 1_700_000_000.0
    stats = {ord("a"): _stats(ord("a"), mean_time_ns=100_000_000.0, last_seen=now)}
    assert newest_key_clears_transition_gate((ord("a"),), {}, 200.0, stats) is True


def test_newest_key_clears_transition_gate_false_when_no_pair_measured_yet():
    """Newest key practiced solo but hasn't typed any bigram with a peer
    yet -- gate stays closed; lesson weighting is what pushes exposure."""
    unlocked = (ord("a"), ord("b"))
    now = 1_700_000_000.0
    stats = {
        ord("a"): _stats(ord("a"), mean_time_ns=100_000_000.0, last_seen=now),
        ord("b"): _stats(ord("b"), mean_time_ns=100_000_000.0, last_seen=now),
    }
    assert newest_key_clears_transition_gate(unlocked, {}, 200.0, stats) is False


def test_newest_key_clears_transition_gate_false_when_weakest_pair_weak():
    unlocked = (ord("a"), ord("b"))
    now = 1_700_000_000.0
    stats = {
        ord("a"): _stats(ord("a"), mean_time_ns=100_000_000.0, last_seen=now),
        ord("b"): _stats(ord("b"), mean_time_ns=100_000_000.0, last_seen=now),
    }
    transitions = {
        Bigram(ord("a"), ord("b")): _transition(
            ord("a"), ord("b"), 400_000_000.0, last_seen=now, attempt_count=4
        ),
        Bigram(ord("b"), ord("a")): _transition(
            ord("b"), ord("a"), 100_000_000.0, last_seen=now, attempt_count=4
        ),
    }
    assert newest_key_clears_transition_gate(unlocked, transitions, 200.0, stats) is False


def test_newest_key_clears_transition_gate_true_when_weakest_pair_solid():
    unlocked = (ord("a"), ord("b"))
    now = 1_700_000_000.0
    stats = {
        ord("a"): _stats(ord("a"), mean_time_ns=100_000_000.0, last_seen=now),
        ord("b"): _stats(ord("b"), mean_time_ns=100_000_000.0, last_seen=now),
    }
    transitions = {
        Bigram(ord("a"), ord("b")): _transition(
            ord("a"), ord("b"), 100_000_000.0, last_seen=now, attempt_count=4
        ),
        Bigram(ord("b"), ord("a")): _transition(
            ord("b"), ord("a"), 100_000_000.0, last_seen=now, attempt_count=4
        ),
    }
    assert newest_key_clears_transition_gate(unlocked, transitions, 200.0, stats) is True


def test_newest_key_transition_gate_requires_entire_stable_cohort():
    unlocked = (ord("a"), ord("b"), ord("c"))
    now = 1_700_000_000.0
    stats = {
        ord("a"): _stats(ord("a"), mean_time_ns=100_000_000.0, last_seen=now),
        ord("b"): _stats(ord("b"), mean_time_ns=100_000_000.0, last_seen=now),
        ord("c"): _stats(ord("c"), mean_time_ns=100_000_000.0, last_seen=now),
    }
    # Only a<->c is measured (and solid); b<->c is never touched at all.
    transitions = {
        Bigram(ord("a"), ord("c")): _transition(
            ord("a"), ord("c"), 100_000_000.0, last_seen=now, attempt_count=4
        ),
        Bigram(ord("c"), ord("a")): _transition(
            ord("c"), ord("a"), 100_000_000.0, last_seen=now, attempt_count=4
        ),
    }
    assert newest_key_clears_transition_gate(unlocked, transitions, 200.0, stats) is False


def test_newest_key_clears_transition_gate_stall_cap_overrides_weak_pair():
    unlocked = (ord("a"), ord("b"))
    now = 1_700_000_000.0
    stats = {
        ord("a"): _stats(ord("a"), mean_time_ns=100_000_000.0, last_seen=now),
        ord("b"): _stats(ord("b"), mean_time_ns=100_000_000.0, last_seen=now),
    }
    transitions = {
        Bigram(ord("a"), ord("b")): _transition(
            ord("a"), ord("b"), 400_000_000.0, last_seen=now, attempt_count=12
        ),
        Bigram(ord("b"), ord("a")): _transition(
            ord("b"), ord("a"), 100_000_000.0, last_seen=now, attempt_count=12
        ),
    }
    assert (
        newest_key_clears_transition_gate(
            unlocked, transitions, 200.0, stats, stall_attempts_cap=12
        )
        is True
    )
    assert (
        newest_key_clears_transition_gate(
            unlocked, transitions, 200.0, stats, stall_attempts_cap=13
        )
        is False
    )
