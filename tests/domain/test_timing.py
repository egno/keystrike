from __future__ import annotations

import statistics

import pytest

from keystrike.domain.models import Keystroke
from keystrike.domain.timing import (
    MIN_INTERVAL_MS,
    TAIL_FACTOR,
    eligible_intervals,
    key_timings,
    weighted_median,
)

A, B, C, X = (ord(c) for c in "abcx")
SP = ord(" ")
MS = 1_000_000


def _stream(*presses: tuple[str, str, float]) -> list[Keystroke]:
    """(target, typed, time in ms) per keystroke."""
    return [
        Keystroke(ord(target), ord(typed), round(t * MS), correct=target == typed)
        for target, typed, t in presses
    ]


def _eligible(stream: list[Keystroke]) -> list[tuple[str, float]]:
    return [(chr(ks.codepoint), ms) for ks, ms in eligible_intervals(stream)]


# --- eligible intervals -----------------------------------------------------------


def test_the_first_press_of_a_session_is_not_timed():
    assert _eligible(_stream(("a", "a", 500), ("b", "b", 700))) == [("b", 200.0)]


def test_a_wrong_first_attempt_is_not_timed():
    stream = _stream(("a", "a", 0), ("b", "x", 200), ("b", "b", 400))
    assert _eligible(stream) == []


def test_the_first_press_after_an_error_is_not_timed():
    """`b` was wrong first, then retried. The next position (`c`) is the first
    press after the error, so it is skipped. The one after (`a`) counts."""
    stream = _stream(
        ("a", "a", 0),
        ("b", "x", 200),
        ("b", "b", 600),
        ("c", "c", 800),
        ("a", "a", 1000),
    )
    assert _eligible(stream) == [("a", 200.0)]


def test_a_retry_is_not_a_new_position():
    stream = _stream(("a", "a", 0), ("b", "x", 100), ("b", "c", 200), ("b", "b", 300))
    assert _eligible(stream) == []


def test_a_rollover_interval_is_not_timed():
    stream = _stream(("a", "a", 0), ("b", "b", MIN_INTERVAL_MS - 1), ("c", "c", 300))
    assert _eligible(stream) == [("c", 300.0 - (MIN_INTERVAL_MS - 1))]
    at_limit = _stream(("a", "a", 0), ("b", "b", MIN_INTERVAL_MS))
    assert _eligible(at_limit) == [("b", MIN_INTERVAL_MS)]


def test_the_space_and_the_press_after_a_space_are_not_timed():
    stream = _stream(("a", "a", 0), (" ", " ", 400), ("b", "b", 500), ("c", "c", 700))
    assert _eligible(stream) == [("c", 200.0)]


# --- weighted median -----------------------------------------------------------


def test_equal_weights_give_the_usual_median():
    assert weighted_median([(1, 1), (3, 1), (2, 1)]) == 2
    assert weighted_median([(1, 1), (2, 1), (3, 1), (10, 1)]) == 2.5


def test_heavier_values_pull_the_median():
    assert weighted_median([(100, 1.0), (300, 0.2), (400, 0.2)]) == 100
    assert weighted_median([(100, 0.2), (300, 1.0), (400, 1.0)]) == 300


def test_weighted_median_of_nothing_is_zero_and_zero_weights_are_ignored():
    assert weighted_median([]) == 0.0
    assert weighted_median([(5, 0.0)]) == 0.0
    assert weighted_median([(5, 0.0), (7, 1.0)]) == 7


# --- key timings ---------------------------------------------------------------


def _letters(*intervals: float, key: str = "a") -> list[Keystroke]:
    """A stream of `key` presses with the given intervals after a `b`."""
    presses = [("b", "b", 0.0)]
    t = 0.0
    for ms in intervals:
        t += ms
        presses.append((key, key, t))
    return _stream(*presses)


def test_key_timing_counts_and_medians():
    goal = 200.0
    timings, space = key_timings([_letters(100, 250, 450, 300)], [1.0], goal, {A})
    t = timings[A]
    assert t.presses == 4
    assert t.over_goal == 3  # 250, 450, 300
    assert t.tail == 1  # 450 > 2 x 200
    assert t.median_ms == statistics.median([100, 250, 450, 300])
    assert t.recent_median_ms == t.median_ms  # one stream
    assert t.sessions == 1
    assert space is None
    assert TAIL_FACTOR == 2.0


def test_recent_median_follows_the_heavier_sessions_while_the_counts_stay_exact():
    new, old = _letters(300, 300, 300), _letters(100, 100, 100)
    timings, _ = key_timings([new, old], [1.0, 0.2], 200.0, {A})
    t = timings[A]
    assert t.presses == 6
    assert t.median_ms == 200.0
    assert t.recent_median_ms == 300.0
    assert t.sessions == 2


def test_sessions_count_only_streams_that_contribute():
    empty = _stream(("a", "a", 0))  # the first press is never timed
    timings, _ = key_timings([_letters(200), empty, _letters(200)], [1, 1, 1], 200.0, {A})
    assert timings[A].sessions == 2


def test_only_the_given_keys_and_keys_with_intervals_are_reported():
    timings, _ = key_timings([_letters(200, 200)], [1.0], 200.0, {A, C})
    assert set(timings) == {A}  # b is not asked for; c has no interval


def test_a_goal_of_zero_counts_nothing_over_the_goal():
    timings, _ = key_timings([_letters(900, 900)], [1.0], 0.0, {A})
    assert (timings[A].over_goal, timings[A].tail) == (0, 0)


def test_the_space_is_reported_on_its_own():
    stream = _stream(
        ("a", "a", 0),
        (" ", " ", 400),  # timed: after a correct letter
        ("b", "b", 500),
        ("c", "x", 700),
        ("c", "c", 800),
        (" ", " ", 1000),  # not timed: first press after an error
        ("a", "a", 1100),
        (" ", " ", 1110),  # not timed: rollover
    )
    timings, space = key_timings([stream], [1.0], 300.0, {A, B, C})
    assert space is not None
    assert (space.presses, space.median_ms, space.over_goal, space.sessions) == (1, 400.0, 1, 1)
    assert SP not in timings
    assert timings == {}  # each letter follows a space, an error, or starts the stream


def test_weights_must_match_the_streams():
    with pytest.raises(ValueError):  # noqa: PT011 - zip(strict=True)
        key_timings([_letters(200)], [], 200.0, {A})
