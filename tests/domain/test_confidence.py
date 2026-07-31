from keystrike.domain.confidence import (
    MIN_CONFIDENCE_ATTEMPTS,
    accuracy_of,
    confidence_of,
    key_attempts,
    key_confidence,
    review_urgency,
    skill_of,
    target_ms_per_char,
    transition_accuracy_of,
    transition_confidence_of,
)
from keystrike.domain.focus import (
    focus_key_from_transition,
    has_weak_unlocked_key,
    practice_weight,
    select_focus,
    select_focus_transition,
)
from keystrike.domain.models import Bigram, KeyStats, TransitionStats
from keystrike.domain.unlock import compute_unlocked


def test_target_ms_per_char():
    assert target_ms_per_char(300) == 200.0


def test_key_confidence_at_target_speed_is_one():
    assert key_confidence(200.0, 200_000_000.0) == 1.0


def test_key_confidence_faster_than_target_is_above_one():
    assert key_confidence(200.0, 100_000_000.0) == 2.0


def test_key_confidence_slower_than_target_is_below_one():
    assert key_confidence(200.0, 400_000_000.0) == 0.5


def test_key_confidence_no_samples_is_zero():
    assert key_confidence(200.0, 0.0) == 0.0


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


def test_accuracy_of_no_errors_is_one():
    assert accuracy_of(_stats(ord("a"), mean_time_ns=200_000_000.0)) == 1.0


def test_accuracy_of_mixes_samples_and_errors():
    stats = _stats(ord("a"), mean_time_ns=200_000_000.0, error_count=10)
    assert accuracy_of(stats) == 0.5


def test_accuracy_of_never_correct_is_zero():
    stats = KeyStats(codepoint=ord("a"), samples=0, mean_time_ns=0.0, error_count=3, last_seen=0.0)
    assert accuracy_of(stats) == 0.0


def test_transition_accuracy_of_uses_mean_when_samples_rounded_to_zero():
    stats = TransitionStats(
        ord("e"),
        ord("o"),
        0,
        196_000_000.0,
        0,
        1.0,
        attempt_count=1,
    )
    assert transition_accuracy_of(stats) == 1.0


def test_confidence_of_scales_down_with_few_attempts():
    stats = {
        ord("a"): KeyStats(
            codepoint=ord("a"),
            samples=1,
            mean_time_ns=100_000_000.0,
            error_count=1,
            last_seen=0.0,
            attempt_count=2,
        ),
    }
    # raw min(speed, accuracy) = min(2.0, 0.5) = 0.5; only 2 attempts -> x0.2
    assert confidence_of(ord("a"), stats, target=200.0) == 0.1


def test_skill_of_ignores_attempt_ramp():
    stats = {
        ord("t"): KeyStats(
            codepoint=ord("t"),
            samples=9,
            mean_time_ns=126_000_000.0,  # speed ~1.59 at target 200ms
            error_count=0,
            last_seen=0.0,
            attempt_count=9,
        ),
    }
    target = 200.0
    assert skill_of(ord("t"), stats, target=target) == 1.0
    assert confidence_of(ord("t"), stats, target=target) == 0.9


def test_skill_of_matches_confidence_at_minimum_attempts():
    stats = {ord("a"): _stats(ord("a"), mean_time_ns=200_000_000.0, error_count=0)}
    target = 200.0
    assert skill_of(ord("a"), stats, target=target) == confidence_of(ord("a"), stats, target=target)


def test_skill_of_unseen_key_is_zero():
    assert skill_of(ord("a"), {}, target=200.0) == 0.0


def test_confidence_of_reaches_full_value_at_minimum_attempts():
    stats = {ord("a"): _stats(ord("a"), mean_time_ns=200_000_000.0, error_count=0)}
    assert key_attempts(stats[ord("a")]) == MIN_CONFIDENCE_ATTEMPTS
    assert confidence_of(ord("a"), stats, target=200.0) == 1.0


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


def test_transition_confidence_scales_down_with_few_attempts():
    stats = {
        Bigram(ord("a"), ord("b")): TransitionStats(
            ord("a"),
            ord("b"),
            samples=3,
            mean_time_ns=200_000_000.0,
            error_count=0,
            last_seen=0.0,
            attempt_count=2,
        ),
    }
    # raw 1.0 x (2/4) = 0.5
    assert transition_confidence_of(ord("a"), ord("b"), stats, target=200.0) == 0.5


def test_transition_confidence_reaches_full_at_minimum_attempts():
    stats = {
        Bigram(ord("a"), ord("b")): _transition(ord("a"), ord("b"), 200_000_000.0, attempt_count=4),
    }
    assert transition_confidence_of(ord("a"), ord("b"), stats, target=200.0) == 1.0


def test_transition_confidence_infers_attempts_when_samples_zeroed_but_timed():
    """Stale cache may zero samples while mean_time_ns remains measured."""
    stats = {
        Bigram(ord("e"), ord("o")): TransitionStats(
            ord("e"),
            ord("o"),
            0,
            196_000_000.0,
            0,
            1.0,
            attempt_count=0,
        ),
    }
    target = target_ms_per_char(300)
    assert transition_confidence_of(ord("e"), ord("o"), stats, target) > 0.0


def test_transition_confidence_infers_attempts_from_samples_when_count_zeroed():
    """Stale cache may store attempt_count=0 while samples/mean remain measured."""
    stats = {
        Bigram(ord("e"), ord("o")): TransitionStats(
            ord("e"),
            ord("o"),
            1,
            196_000_000.0,
            0,
            1.0,
            attempt_count=0,
        ),
    }
    target = target_ms_per_char(300)
    assert transition_confidence_of(ord("e"), ord("o"), stats, target) > 0.0


def test_transition_confidence_infers_attempts_from_mean_when_all_counts_zeroed():
    """Pre-fix cache wrote samples=0 and attempt_count=0 while mean_time_ns stayed."""
    stats = {
        Bigram(ord("e"), ord("o")): TransitionStats(
            ord("e"),
            ord("o"),
            0,
            196_000_000.0,
            0,
            1.0,
            attempt_count=0,
        ),
    }
    target = target_ms_per_char(300)
    confidence = transition_confidence_of(ord("e"), ord("o"), stats, target)
    assert confidence > 0.0
    assert confidence < 1.0


def test_confidence_of_penalizes_frequent_errors():
    # Fast (2.0 speed) but wrong half the time -> min(2.0, 0.5) = 0.5, not mastered.
    stats = {ord("a"): _stats(ord("a"), mean_time_ns=100_000_000.0, error_count=10)}
    assert confidence_of(ord("a"), stats, target=200.0) == 0.5


def test_compute_unlocked_stalls_on_high_error_rate_despite_fast_speed():
    learn_order = (1, 2, 3, 4)
    # speed 2.0, but only 50% accuracy -> min(2.0, 0.5) = 0.5 < threshold
    stats = {1: _stats(1, mean_time_ns=100_000_000.0, error_count=10)}
    unlocked = compute_unlocked(
        learn_order, alphabet_size=1, stats=stats, target=200.0, threshold=1.5
    )
    assert unlocked == (1,)


def test_confidence_of_unseen_key_is_zero():
    assert confidence_of(ord("a"), {}, target=200.0) == 0.0


def test_confidence_of_uses_mean_time():
    stats = {ord("a"): _stats(ord("a"), mean_time_ns=200_000_000.0)}
    assert confidence_of(ord("a"), stats, target=200.0) == 1.0


def test_confidence_of_rounds_near_goal_to_mastery_threshold():
    # Raw ~0.996 reads as 1.00 everywhere — no "weak" label vs 1.00 display mismatch.
    stats = {ord("i"): _stats(ord("i"), mean_time_ns=200_000_000.0 / 0.996)}
    assert confidence_of(ord("i"), stats, target=200.0) == 1.0


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


def test_compute_unlocked_ignores_weak_same_key_transition():
    learn_order = tuple(ord(c) for c in "eabcdfghm")
    stats = {cp: _stats(cp, mean_time_ns=100_000_000.0) for cp in learn_order[:8]}
    transitions = {
        Bigram(ord("e"), ord("e")): TransitionStats(
            ord("e"),
            ord("e"),
            samples=10,
            mean_time_ns=400_000_000.0,
            error_count=0,
            last_seen=0.0,
            attempt_count=10,
        ),
    }
    unlocked = compute_unlocked(
        learn_order,
        alphabet_size=8,
        stats=stats,
        target=200.0,
        transitions=transitions,
    )
    assert unlocked == learn_order[:9]
    assert unlocked[-1] == ord("m")


def test_compute_unlocked_stalls_on_weak_cross_key_transition():
    learn_order = tuple(ord(c) for c in "eabcdfghm")
    stats = {cp: _stats(cp, mean_time_ns=100_000_000.0) for cp in learn_order[:8]}
    transitions = {
        Bigram(ord("e"), ord("a")): TransitionStats(
            ord("e"),
            ord("a"),
            samples=10,
            mean_time_ns=400_000_000.0,
            error_count=0,
            last_seen=0.0,
            attempt_count=10,
        ),
    }
    unlocked = compute_unlocked(
        learn_order,
        alphabet_size=8,
        stats=stats,
        target=200.0,
        transitions=transitions,
    )
    assert unlocked == learn_order[:8]
    assert ord("m") not in unlocked


def test_compute_unlocked_advances_when_measured_transitions_meet_threshold():
    learn_order = tuple(ord(c) for c in "eabcdfghm")
    stats = {cp: _stats(cp, mean_time_ns=100_000_000.0) for cp in learn_order[:8]}
    transitions = {
        Bigram(ord("e"), ord("e")): _transition(
            ord("e"),
            ord("e"),
            100_000_000.0,
            attempt_count=10,
        ),
    }
    unlocked = compute_unlocked(
        learn_order,
        alphabet_size=8,
        stats=stats,
        target=200.0,
        transitions=transitions,
    )
    assert unlocked == learn_order[:9]
    assert unlocked[-1] == ord("m")


def test_select_focus_picks_weakest_unlocked_key():
    stats = {
        1: _stats(1, mean_time_ns=100_000_000.0),  # confidence 2.0
        2: _stats(2, mean_time_ns=400_000_000.0),  # confidence 0.5
    }
    assert select_focus((1, 2), stats, target=200.0, now=1000.0) == 2


def test_has_weak_unlocked_key_true_when_any_below_threshold():
    stats = {
        1: _stats(1, mean_time_ns=200_000_000.0),
        2: _stats(2, mean_time_ns=400_000_000.0),
    }
    assert has_weak_unlocked_key((1, 2), stats, target=200.0) is True


def test_has_weak_unlocked_key_false_when_all_confident():
    stats = {
        1: _stats(1, mean_time_ns=200_000_000.0),
        2: _stats(2, mean_time_ns=100_000_000.0),
    }
    assert has_weak_unlocked_key((1, 2), stats, target=200.0) is False


def test_has_weak_unlocked_key_true_for_never_practiced():
    stats = {1: _stats(1, mean_time_ns=200_000_000.0)}
    assert has_weak_unlocked_key((1, 2), stats, target=200.0) is True


def test_select_focus_prefers_never_practiced_key():
    stats = {1: _stats(1, mean_time_ns=100_000_000.0)}
    assert select_focus((1, 2), stats, target=200.0, now=1000.0) == 2


def test_review_urgency_never_seen_or_fresh_is_zero():
    assert review_urgency(0.0, 1_000_000.0) == 0.0
    assert review_urgency(1000.0, 1000.0) == 0.0
    assert review_urgency(1000.0, 999.0) == 0.0


def test_review_urgency_rises_after_one_day_and_peaks_by_three():
    base = 1_000_000.0
    day = 86_400.0
    assert review_urgency(base, base + day) == 0.0
    mid = review_urgency(base, base + 2 * day)
    assert 0.0 < mid < 1.0
    assert review_urgency(base, base + 3 * day) == 1.0
    assert review_urgency(base, base + 7 * day) == 1.0


def test_practice_weight_boosts_stale_mastered_key():
    assert practice_weight(1.0, urgency=1.0) == 2.0


def test_select_focus_picks_stale_over_slightly_weaker_recent():
    now = 1_000_000.0
    five_days = 5 * 86_400.0
    stats = {
        1: _stats(1, mean_time_ns=210_000_000.0, last_seen=now - five_days),  # ~0.95
        2: _stats(2, mean_time_ns=235_000_000.0, last_seen=now),  # ~0.85
    }
    assert select_focus((1, 2), stats, target=200.0, now=now) == 1


def test_practice_weight_unpracticed_key_is_max_biased():
    assert practice_weight(0.0, max_bias=3.0) == 4.0


def test_practice_weight_mastered_key_is_baseline():
    assert practice_weight(1.0, max_bias=3.0) == 1.0


def test_practice_weight_caps_above_mastery_threshold():
    # A key faster than target shouldn't get pushed below baseline weight.
    assert practice_weight(2.0, max_bias=3.0) == 1.0


def test_practice_weight_scales_linearly_between_zero_and_one():
    assert practice_weight(0.5, max_bias=3.0) == 2.5


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


def test_select_focus_transition_returns_none_without_data():
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


def test_select_focus_transition_returns_none_when_no_measured_unlocked_pairs():
    unlocked = (ord("a"), ord("b"))
    transitions = {
        Bigram(ord("y"), ord("z")): _transition(
            ord("y"),
            ord("z"),
            100_000_000.0,
            last_seen=1_700_000_000.0,
        ),
    }
    assert select_focus_transition(unlocked, transitions, 200.0, now=1_700_000_000.0) is None


def test_focus_key_from_transition_uses_next_endpoint():
    assert focus_key_from_transition(ord("t"), ord("h")) == ord("h")
