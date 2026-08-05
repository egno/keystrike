import pytest

from keystrike.domain.confidence import (
    MIN_CONFIDENCE_ATTEMPTS,
    attempts_of,
    skill_from_stats,
    skill_of,
    target_ms_per_char,
)
from keystrike.domain.enums import FocusKind
from keystrike.domain.focus import (
    FocusReason,
    blocks_transition_focus,
    focus_key_from_transition,
    remedial_focus,
    select_focus,
    select_focus_transition,
)
from keystrike.domain.models import Bigram, KeyStats, TransitionStats


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


def test_remedial_focus_picks_weakest_key_in_lesson_alphabet():
    """Weakest key within the remedial pool, not the globally weakest key."""
    now = 1_700_000_000.0
    at_target = 200_000_000.0
    a, s, h, d = ord("a"), ord("s"), ord("h"), ord("d")
    stats = {
        a: KeyStats(a, 10, at_target, 0, now, attempt_count=10),
        s: KeyStats(s, 10, at_target, 0, now, attempt_count=10),
        h: KeyStats(h, 10, at_target / 0.2, 0, now, attempt_count=10),
        d: KeyStats(d, 10, at_target / 0.6, 0, now, attempt_count=10),
    }
    target = target_ms_per_char(300)
    assert select_focus((a, s, h, d), stats, target, now) == h

    result = remedial_focus((a, d), (a, s, h, d), stats, {}, target, now=now)
    assert result == (d, None)


def test_remedial_focus_none_when_alphabet_disjoint_from_unlocked():
    now = 1_700_000_000.0
    at_target = 200_000_000.0
    a = ord("a")
    stats = {a: KeyStats(a, 10, at_target, 0, now, attempt_count=10)}
    target = target_ms_per_char(300)

    assert remedial_focus((ord("z"),), (a,), stats, {}, target, now=now) is None


def test_select_focus_picks_weakest_unlocked_key():
    stats = {
        1: _stats(1, mean_time_ns=100_000_000.0),  # confidence 2.0
        2: _stats(2, mean_time_ns=400_000_000.0),  # confidence 0.5
    }
    assert select_focus((1, 2), stats, target=200.0, now=1000.0) == 2


def test_blocks_transition_focus_true_when_key_below_attempt_floor():
    stats = {
        ord("t"): KeyStats(
            ord("t"),
            samples=9,
            mean_time_ns=125_000_000.0,
            error_count=0,
            last_seen=0.0,
            attempt_count=9,
        ),
    }
    target = target_ms_per_char(300)
    assert skill_of(ord("t"), stats, target=target) == 1.0
    assert blocks_transition_focus((ord("t"),), stats, target=target) is True


def test_blocks_transition_focus_true_for_never_practiced():
    stats = {1: _stats(1, mean_time_ns=200_000_000.0)}
    assert blocks_transition_focus((1, 2), stats, target=200.0) is True


def test_blocks_transition_focus_includes_never_practiced_key():
    a, s, h = ord("a"), ord("s"), ord("h")
    stats = {
        a: _stats(a, mean_time_ns=200_000_000.0),
        s: _stats(s, mean_time_ns=200_000_000.0),
    }
    assert blocks_transition_focus((a, s, h), stats, target=200.0) is True


def test_blocks_transition_focus_true_for_measured_weak_key():
    h = ord("h")
    stats = {h: _stats(h, mean_time_ns=400_000_000.0)}
    assert skill_of(h, stats, target=200.0) < 1.0
    assert blocks_transition_focus((h,), stats, target=200.0) is True


def test_select_focus_prefers_never_practiced_key():
    stats = {1: _stats(1, mean_time_ns=100_000_000.0)}
    assert select_focus((1, 2), stats, target=200.0, now=1000.0) == 2


def test_select_focus_stays_on_calibrating_key_over_stale_mastered_peer():
    """A key still short of the attempt floor must not lose focus to an
    already-mastered, stale peer -- that peer's review-urgency discount can
    make it look "weaker" by raw score, but it has already cleared both
    conditions (skill + attempts) so it must not preempt an in-progress key."""
    now = 1_700_000_000.0
    five_days = 5 * 86_400.0
    at_target = 200_000_000.0
    calibrating = KeyStats(
        codepoint=1,
        samples=8,
        mean_time_ns=at_target,
        error_count=0,
        last_seen=now,
        attempt_count=8,
    )
    mastered_stale = KeyStats(
        codepoint=2,
        samples=10,
        mean_time_ns=at_target,
        error_count=0,
        last_seen=now - five_days,
        attempt_count=10,
    )
    stats = {1: calibrating, 2: mastered_stale}
    target = 200.0
    assert skill_of(1, stats, target) == 1.0
    assert attempts_of(calibrating) < MIN_CONFIDENCE_ATTEMPTS
    assert skill_of(2, stats, target) == 1.0
    assert attempts_of(mastered_stale) >= MIN_CONFIDENCE_ATTEMPTS
    # Without the stickiness fix, key 2's review-urgency discount would drop
    # its score below key 1's, stealing focus mid-calibration.
    assert select_focus((1, 2), stats, target=target, now=now) == 1


def test_select_focus_picks_stale_over_slightly_weaker_recent():
    now = 1_000_000.0
    five_days = 5 * 86_400.0
    stats = {
        1: _stats(1, mean_time_ns=210_000_000.0, last_seen=now - five_days),  # ~0.95
        2: _stats(2, mean_time_ns=235_000_000.0, last_seen=now),  # ~0.85
    }
    assert select_focus((1, 2), stats, target=200.0, now=now) == 1


def test_select_focus_transition_ignores_same_key_pairs():
    now = 1_700_000_000.0
    unlocked = (ord("e"), ord("a"))
    transitions = {
        Bigram(ord("e"), ord("e")): _transition(
            ord("e"),
            ord("e"),
            400_000_000.0,
            last_seen=now,
            attempt_count=10,
        ),
        Bigram(ord("a"), ord("a")): _transition(
            ord("a"),
            ord("a"),
            400_000_000.0,
            last_seen=now,
            attempt_count=10,
        ),
    }
    assert select_focus_transition(unlocked, transitions, 200.0, now) is None


def test_select_focus_transition_skips_unmeasured_when_unlocked_key_unpracticed():
    now = 1_700_000_000.0
    unlocked = (ord("e"), ord("a"))
    transitions = {
        Bigram(ord("e"), ord("e")): _transition(
            ord("e"),
            ord("e"),
            400_000_000.0,
            last_seen=now,
            attempt_count=10,
        ),
    }
    assert select_focus_transition(unlocked, transitions, 200.0, now) is None


def test_select_focus_transition_never_picks_same_key_even_when_weakest():
    now = 1_700_000_000.0
    unlocked = (ord("a"), ord("b"))
    fast = 100_000_000.0
    transitions = {
        Bigram(ord("a"), ord("a")): _transition(
            ord("a"),
            ord("a"),
            400_000_000.0,
            last_seen=now,
            attempt_count=10,
        ),
        Bigram(ord("a"), ord("b")): _transition(
            ord("a"),
            ord("b"),
            fast,
            last_seen=now,
            attempt_count=10,
        ),
        Bigram(ord("b"), ord("a")): _transition(
            ord("b"),
            ord("a"),
            fast,
            last_seen=now,
            attempt_count=10,
        ),
        Bigram(ord("b"), ord("b")): _transition(
            ord("b"),
            ord("b"),
            400_000_000.0,
            last_seen=now,
            attempt_count=10,
        ),
    }
    result = select_focus_transition(unlocked, transitions, 200.0, now)
    assert result is not None
    assert result[0] != result[1]


def test_select_focus_transition_picks_stale_over_slightly_weaker_recent():
    now = 1_000_000.0
    five_days = 5 * 86_400.0
    unlocked = (ord("a"), ord("b"))
    fast = 100_000_000.0
    transitions = {
        Bigram(ord("a"), ord("a")): _transition(ord("a"), ord("a"), fast, last_seen=now),
        Bigram(ord("a"), ord("b")): _transition(
            ord("a"),
            ord("b"),
            210_000_000.0,
            last_seen=now - five_days,
        ),
        Bigram(ord("b"), ord("a")): _transition(ord("b"), ord("a"), 235_000_000.0, last_seen=now),
        Bigram(ord("b"), ord("b")): _transition(ord("b"), ord("b"), fast, last_seen=now),
    }
    assert select_focus_transition(unlocked, transitions, 200.0, now) == (ord("a"), ord("b"))


def test_select_focus_transition_stays_on_calibrating_pair_over_stale_mastered_peer():
    """Mirrors `test_select_focus_stays_on_calibrating_key_over_stale_mastered_peer`
    for bigrams: an in-progress pair (below the attempt floor) must not lose
    focus to an already-cleared, merely-stale measured pair."""
    now = 1_700_000_000.0
    five_days = 5 * 86_400.0
    unlocked = (ord("a"), ord("b"), ord("c"))
    calibrating = Bigram(ord("a"), ord("b"))
    mastered_stale = Bigram(ord("b"), ord("c"))
    transitions = {
        calibrating: _transition(*calibrating, 200_000_000.0, last_seen=now, attempt_count=2),
        mastered_stale: _transition(
            *mastered_stale, 200_000_000.0, last_seen=now - five_days, attempt_count=10
        ),
    }
    target = 200.0
    assert skill_from_stats(transitions[calibrating], target) == 1.0
    assert attempts_of(transitions[calibrating]) < 4  # below MIN_TRANSITION_CONFIDENCE_ATTEMPTS
    assert skill_from_stats(transitions[mastered_stale], target) == 1.0
    assert attempts_of(transitions[mastered_stale]) >= 4
    assert select_focus_transition(unlocked, transitions, target, now) == calibrating


def test_select_focus_transition_returns_none_without_unlocked_pairs():
    assert select_focus_transition((), {}, target=200.0, now=1000.0) is None
    assert select_focus_transition((ord("a"),), {}, target=200.0, now=1000.0) is None


def test_select_focus_transition_picks_unmeasured_pair_when_all_keys_practiced():
    stats = {
        1: KeyStats(1, 10, 200_000_000.0, 0, 1.0, attempt_count=10),
        2: KeyStats(2, 10, 200_000_000.0, 0, 1.0, attempt_count=10),
    }
    assert select_focus_transition((1, 2), {}, target=200.0, now=1000.0, key_stats=stats) == (
        1,
        2,
    )


def test_select_focus_transition_skips_unmeasured_pair_on_cold_start():
    assert select_focus_transition((1, 2), {}, target=200.0, now=1000.0) is None


def test_select_focus_transition_ignores_unmeasured_pairs():
    unlocked = (ord("a"), ord("b"), ord("c"))
    now = 1_700_000_000.0
    fast = 100_000_000.0
    transitions = {
        Bigram(ord("a"), ord("b")): _transition(
            ord("a"),
            ord("b"),
            400_000_000.0,
            last_seen=now,
            attempt_count=10,
        ),
        Bigram(ord("b"), ord("c")): _transition(
            ord("b"),
            ord("c"),
            fast,
            last_seen=now,
            attempt_count=10,
        ),
    }
    assert select_focus_transition(unlocked, transitions, 200.0, now) == (ord("a"), ord("b"))


def test_select_focus_transition_prefers_newest_key_over_older_measured_pair():
    """Once a third key is unlocked, its bigrams should win focus over an
    already-measured (and merely weak, not unmeasured) older pair, so a
    freshly-opened letter gets bigram practice right away."""
    unlocked = (ord("a"), ord("b"), ord("c"))
    now = 1_700_000_000.0
    stats = {
        ord("a"): KeyStats(ord("a"), 10, 200_000_000.0, 0, now, attempt_count=10),
        ord("b"): KeyStats(ord("b"), 10, 200_000_000.0, 0, now, attempt_count=10),
        ord("c"): KeyStats(ord("c"), 10, 200_000_000.0, 0, now, attempt_count=10),
    }
    transitions = {
        Bigram(ord("a"), ord("b")): _transition(
            ord("a"),
            ord("b"),
            400_000_000.0,
            last_seen=now,
            attempt_count=10,
        ),
    }
    # c is unlocked and practiced solo, but none of its transitions are
    # measured yet -- it should still win over the already-measured (a, b).
    result = select_focus_transition(unlocked, transitions, 200.0, now, key_stats=stats)
    assert result is not None
    assert ord("c") in result


def test_select_focus_transition_uses_measured_pairs_once_newest_key_has_data():
    """Once the newest key has its own measured transition, ordinary
    weakest-pair scoring resumes -- no permanent bias toward the newest key."""
    unlocked = (ord("a"), ord("b"), ord("c"))
    now = 1_700_000_000.0
    fast = 100_000_000.0
    stats = {
        ord("a"): KeyStats(ord("a"), 10, 200_000_000.0, 0, now, attempt_count=10),
        ord("b"): KeyStats(ord("b"), 10, 200_000_000.0, 0, now, attempt_count=10),
        ord("c"): KeyStats(ord("c"), 10, 200_000_000.0, 0, now, attempt_count=10),
    }
    transitions = {
        Bigram(ord("a"), ord("b")): _transition(
            ord("a"),
            ord("b"),
            400_000_000.0,
            last_seen=now,
            attempt_count=10,
        ),
        Bigram(ord("b"), ord("c")): _transition(
            ord("b"),
            ord("c"),
            fast,
            last_seen=now,
            attempt_count=10,
        ),
    }
    assert select_focus_transition(unlocked, transitions, 200.0, now, key_stats=stats) == (
        ord("a"),
        ord("b"),
    )


def test_select_focus_transition_falls_back_to_unmeasured_unlocked_pair():
    unlocked = (ord("a"), ord("b"))
    stats = {
        ord("a"): KeyStats(ord("a"), 10, 200_000_000.0, 0, 1.0, attempt_count=10),
        ord("b"): KeyStats(ord("b"), 10, 200_000_000.0, 0, 1.0, attempt_count=10),
    }
    transitions = {
        Bigram(ord("y"), ord("z")): _transition(
            ord("y"),
            ord("z"),
            100_000_000.0,
            last_seen=1_700_000_000.0,
        ),
    }
    assert select_focus_transition(
        unlocked, transitions, 200.0, now=1_700_000_000.0, key_stats=stats
    ) == (ord("a"), ord("b"))


def test_focus_key_from_transition_uses_next_endpoint():
    assert focus_key_from_transition(ord("t"), ord("h")) == ord("h")


def test_key_attempt_floor_blocks_transition_focus():
    cp = ord("a")
    stats = {
        cp: KeyStats(cp, 9, 100_000_000.0, 0, 1.0, attempt_count=9),
    }
    assert blocks_transition_focus((cp,), stats, 200.0, min_attempts=10)


def test_sparse_old_transition_does_not_preempt_gating_cohort():
    a, b, c = map(ord, "abc")
    gate = Bigram(b, c)
    old = Bigram(a, b)
    transitions = {
        old: _transition(a, b, 400_000_000.0, attempt_count=3),
    }
    assert (
        select_focus_transition(
            (a, b, c),
            transitions,
            200.0,
            1_000.0,
            gating_candidates=(gate,),
            min_attempts=4,
        )
        == gate
    )


def test_genuine_old_transition_regression_preempts_gating_cohort():
    a, b, c = map(ord, "abc")
    gate = Bigram(b, c)
    old = Bigram(a, b)
    transitions = {
        old: _transition(a, b, 400_000_000.0, attempt_count=4),
    }
    assert (
        select_focus_transition(
            (a, b, c),
            transitions,
            200.0,
            1_000.0,
            gating_candidates=(gate,),
            min_attempts=4,
        )
        == old
    )
