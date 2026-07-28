from keystrike.domain.regression import estimate_sessions_to_goal


def test_already_at_goal_returns_zero():
    assert estimate_sessions_to_goal([100.0, 100.0], target_time_ns=150.0) == 0


def test_too_few_samples_returns_none():
    assert estimate_sessions_to_goal([100.0], target_time_ns=50.0) is None
    assert estimate_sessions_to_goal([], target_time_ns=50.0) is None


def test_improving_linear_trend_predicts_a_positive_lookahead():
    # Decreasing by 10ns per attempt; goal is comfortably below the last sample.
    samples = [200.0, 190.0, 180.0, 170.0, 160.0]
    result = estimate_sessions_to_goal(samples, target_time_ns=140.0)
    assert result is not None
    assert result > 0


def test_flat_trend_never_reaches_a_lower_goal():
    samples = [200.0] * 5
    assert estimate_sessions_to_goal(samples, target_time_ns=100.0) is None


def test_worsening_trend_never_reaches_goal():
    samples = [100.0, 110.0, 120.0, 130.0, 140.0]
    assert estimate_sessions_to_goal(samples, target_time_ns=50.0) is None


def test_uses_at_most_last_30_samples():
    # 40 old bad samples followed by 10 already-at-goal samples: only the
    # last 30 should matter, and the tail is already at goal.
    samples = [1000.0] * 40 + [50.0] * 10
    assert estimate_sessions_to_goal(samples, target_time_ns=60.0) == 0


def test_quadratic_degree_used_between_eleven_and_twenty_samples():
    # 15 samples, accelerating improvement (quadratic-shaped decay).
    samples = [200.0 - i * i for i in range(15)]
    result = estimate_sessions_to_goal(samples, target_time_ns=samples[-1] - 5)
    assert result is not None


def test_cubic_degree_used_above_twenty_samples():
    samples = [300.0 - i * 1.5 for i in range(25)]
    result = estimate_sessions_to_goal(samples, target_time_ns=samples[-1] - 10)
    assert result is not None
