from keystrike.domain.focus import newest_key_unmeasured_pairs
from keystrike.domain.models import Bigram, KeyStats, TransitionStats
from keystrike.domain.newest_key import effective_gating_bigram_limit, newest_key_gating_cohort


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


def test_newest_key_unmeasured_pairs_excludes_unpracticed_cascade_key():
    """A key unlocked by cascade (no KeyStats yet) shouldn't get bigram
    candidacy just for sitting next to the newest practiced key."""
    unlocked = (ord("a"), ord("s"), ord("h"), ord("d"), ord("l"))
    now = 1_700_000_000.0
    stats = {
        cp: KeyStats(cp, 10, 200_000_000.0, 0, now, attempt_count=10)
        for cp in (ord("a"), ord("s"), ord("h"), ord("d"))
    }
    pairs = newest_key_unmeasured_pairs(unlocked, {}, stats)
    assert pairs
    assert all(ord("l") not in (p.prev_cp, p.next_cp) for p in pairs)
    assert all(ord("d") in (p.prev_cp, p.next_cp) for p in pairs)


def test_newest_key_unmeasured_pairs_empty_once_newest_has_any_measured_pair():
    unlocked = (ord("a"), ord("s"), ord("d"))
    now = 1_700_000_000.0
    stats = {
        cp: KeyStats(cp, 10, 200_000_000.0, 0, now, attempt_count=10)
        for cp in (ord("a"), ord("s"), ord("d"))
    }
    transitions = {
        Bigram(ord("s"), ord("d")): _transition(
            ord("s"), ord("d"), 200_000_000.0, last_seen=now, attempt_count=10
        ),
    }
    assert newest_key_unmeasured_pairs(unlocked, transitions, stats) == []


def test_gating_cohort_is_bounded_deterministic_and_measurement_independent():
    unlocked = tuple(map(ord, "abcd"))
    stats = {cp: _stats(cp, mean_time_ns=100_000_000.0) for cp in unlocked}
    expected = (
        Bigram(ord("b"), ord("d")),
        Bigram(ord("d"), ord("b")),
        Bigram(ord("c"), ord("d")),
        Bigram(ord("d"), ord("c")),
    )
    assert newest_key_gating_cohort(unlocked, stats) == expected
    assert newest_key_gating_cohort(unlocked, stats) == expected


def test_gating_cohort_limit_is_configurable_and_clamped():
    unlocked = tuple(map(ord, "abcd"))
    stats = {cp: _stats(cp, mean_time_ns=100_000_000.0) for cp in unlocked}
    assert len(newest_key_gating_cohort(unlocked, stats, limit=2)) == 2
    assert len(newest_key_gating_cohort(unlocked, stats, limit=3)) == 3
    assert len(newest_key_gating_cohort(unlocked, stats, limit=4)) == 4
    assert effective_gating_bigram_limit(0) == 2
    assert effective_gating_bigram_limit(99) == 4
