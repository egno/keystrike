from keystrike.domain.models import Bigram, KeyStats
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
