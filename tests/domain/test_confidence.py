from keystrike.domain.confidence import (
    MIN_CONFIDENCE_ATTEMPTS,
    accuracy_of,
    compute_unlocked,
    confidence_of,
    focus_key_from_transition,
    key_attempts,
    key_confidence,
    practice_weight,
    review_urgency,
    select_focus,
    select_focus_transition,
    target_ms_per_char,
    transition_confidence_of,
)
from keystrike.domain.models import KeyStats, TransitionStats


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
    # raw speed×accuracy = 2.0 × 0.5 = 1.0; only 2 attempts → ×0.2
    assert confidence_of(ord("a"), stats, target=200.0) == 0.2


def test_confidence_of_reaches_full_value_at_minimum_attempts():
    stats = {ord("a"): _stats(ord("a"), mean_time_ns=200_000_000.0, error_count=0)}
    assert key_attempts(stats[ord("a")]) == MIN_CONFIDENCE_ATTEMPTS
    assert confidence_of(ord("a"), stats, target=200.0) == 1.0


def test_compute_unlocked_stalls_when_sparse_key_looks_fast():
    learn_order = (1, 2, 3)
    stats = {
        1: _stats(1, mean_time_ns=100_000_000.0),
        2: KeyStats(
            2, samples=1, mean_time_ns=100_000_000.0, error_count=1, last_seen=0.0,
            attempt_count=2,
        ),
    }
    unlocked = compute_unlocked(learn_order, alphabet_size=2, stats=stats, target=200.0)
    assert unlocked == (1, 2)


def test_transition_confidence_scales_down_with_few_attempts():
    stats = {
        "ab": TransitionStats(
            ord("a"), ord("b"), samples=3, mean_time_ns=200_000_000.0,
            error_count=0, last_seen=0.0, attempt_count=2,
        ),
    }
    # raw 1.0 × (2/4) = 0.5
    assert transition_confidence_of(ord("a"), ord("b"), stats, target=200.0) == 0.5


def test_transition_confidence_reaches_full_at_minimum_attempts():
    stats = {
        "ab": _transition(ord("a"), ord("b"), 200_000_000.0, attempt_count=4),
    }
    assert transition_confidence_of(ord("a"), ord("b"), stats, target=200.0) == 1.0


def test_confidence_of_penalizes_frequent_errors():
    # Fast (2.0 speed-confidence) but wrong half the time -> 1.0, not "mastered".
    stats = {ord("a"): _stats(ord("a"), mean_time_ns=100_000_000.0, error_count=10)}
    assert confidence_of(ord("a"), stats, target=200.0) == 1.0


def test_compute_unlocked_stalls_on_high_error_rate_despite_fast_speed():
    learn_order = (1, 2, 3, 4)
    # speed-confidence 2.0, but only 50% accuracy -> combined 1.0 < threshold
    stats = {1: _stats(1, mean_time_ns=100_000_000.0, error_count=10)}
    unlocked = compute_unlocked(learn_order, alphabet_size=1, stats=stats, target=200.0,
                                 threshold=1.5)
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


def test_select_focus_picks_weakest_unlocked_key():
    stats = {
        1: _stats(1, mean_time_ns=100_000_000.0),  # confidence 2.0
        2: _stats(2, mean_time_ns=400_000_000.0),  # confidence 0.5
    }
    assert select_focus((1, 2), stats, target=200.0, now=1000.0) == 2


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


def test_select_focus_transition_picks_stale_over_slightly_weaker_recent():
    now = 1_000_000.0
    five_days = 5 * 86_400.0
    unlocked = (ord("a"), ord("b"))
    fast = 100_000_000.0
    transitions = {
        "aa": _transition(ord("a"), ord("a"), fast, last_seen=now),
        "ab": _transition(ord("a"), ord("b"), 210_000_000.0, last_seen=now - five_days),
        "ba": _transition(ord("b"), ord("a"), 235_000_000.0, last_seen=now),
        "bb": _transition(ord("b"), ord("b"), fast, last_seen=now),
    }
    assert select_focus_transition(unlocked, transitions, 200.0, now) == (ord("a"), ord("b"))


def test_select_focus_transition_returns_none_without_data():
    assert select_focus_transition((1, 2), {}, target=200.0, now=1000.0) is None


def test_focus_key_from_transition_uses_next_endpoint():
    assert focus_key_from_transition(ord("t"), ord("h")) == ord("h")
