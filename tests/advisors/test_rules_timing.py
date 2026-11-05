"""Speed advice from per-key timing: the recency-weighted median of the
eligible intervals, with a 5% dead band around the goal."""

from __future__ import annotations

import pytest

from keystrike.advisors import rules
from keystrike.domain.advice import (
    AdviceDigest,
    AdvisorContext,
    CourseState,
    Coverage,
    KeyTiming,
    Kind,
    Reason,
)
from keystrike.domain.keystroke_insights import KeystrokeInsights
from keystrike.domain.models import KeyTally

LETTERS = "etaoinsrm"
S, M = ord("s"), ord("m")
GOAL_CPM = 207  # 60000 / 207 = 289.9 ms: the 290 ms goal
MS = 1_000_000


def _tally(attempts: int, errors: int = 0, mean_ms: float = 250.0) -> KeyTally:
    samples = attempts - errors
    return KeyTally(samples, int(samples * mean_ms * MS), errors, attempts)


def _timing(recent_median_ms: float, presses: int = 60, sessions: int = 4) -> KeyTiming:
    return KeyTiming(
        presses=presses,
        over_goal=presses // 2,
        tail=0,
        median_ms=recent_median_ms,
        recent_median_ms=recent_median_ms,
        sessions=sessions,
    )


def _ctx(
    timing: dict[int, KeyTiming],
    *,
    tallies: dict[int, KeyTally] | None = None,
    target_cpm: int = GOAL_CPM,
) -> AdvisorContext:
    keys = tallies or {cp: _tally(100) for cp in timing}
    unlocked = tuple(ord(c) for c in LETTERS)
    return AdvisorContext(
        layout="qwerty",
        sessions=(),
        course=CourseState(unlocked=unlocked, target_cpm=target_cpm, confidence={}),
        digest=AdviceDigest(keys=keys, timing=timing),
        coverage=Coverage(digest_sessions=10, stream_sessions=6),
        insights=KeystrokeInsights(),
    )


async def _speed_keys(ctx: AdvisorContext) -> list[int]:
    advice = await rules.rules_advisor(ctx)
    return [
        r.keys[0]
        for r in advice.recommendations
        if r.kind is Kind.EMPHASIZE and r.reason is Reason.SPEED
    ]


async def test_an_m_like_key_well_over_the_goal_is_flagged():
    ctx = _ctx({M: _timing(354, presses=60, sessions=4)})
    advice = await rules.rules_advisor(ctx)
    (rec,) = advice.recommendations
    assert (rec.kind, rec.keys, rec.reason) == (Kind.EMPHASIZE, (M,), Reason.SPEED)
    goal = ctx.course.goal_ms
    assert rec.strength == pytest.approx(min(1.0, (354 / goal - 1) / 0.5))
    ev = rec.evidence
    assert (ev.events, ev.opportunities, ev.sessions) == (30, 60, 4)


@pytest.mark.parametrize(
    "timing",
    [
        _timing(354, presses=19, sessions=4),  # too few presses
        _timing(354, presses=60, sessions=1),  # one session only
        _timing(300, presses=60, sessions=4),  # within 5% of the goal
    ],
    ids=["19-presses", "1-session", "within-5pct"],
)
async def test_an_m_like_key_is_not_flagged_without_enough_evidence_or_margin(
    timing: KeyTiming,
):
    assert await _speed_keys(_ctx({M: timing})) == []


async def test_a_high_mean_does_not_flag_a_key_whose_recent_median_is_at_the_goal():
    """The tally mean is 450 ms (long pauses), but the recent median is at the goal."""
    timing = KeyTiming(
        presses=60, over_goal=20, tail=10, median_ms=380, recent_median_ms=290, sessions=4
    )
    ctx = _ctx({M: timing}, tallies={M: _tally(100, mean_ms=450)})
    assert await _speed_keys(ctx) == []


async def test_a_slow_mean_without_timing_gives_no_speed_advice():
    """No timing: silence, not a guess from the mean."""
    ctx = _ctx({}, tallies={M: _tally(100, mean_ms=600)})
    assert await _speed_keys(ctx) == []


async def test_no_goal_gives_no_speed_advice():
    assert await _speed_keys(_ctx({M: _timing(900)}, target_cpm=0)) == []


async def test_learner_with_slow_m_flags_only_m_and_not_s_at_296_ms():
    """The acceptance case. Nine unlocked letters, a 290 ms goal. `m` has a
    recent median of 354 ms over 69 eligible presses in 6 sessions; the 46% of
    its raw intervals that came right after a space are already left out of
    the timing. Every other key is at 213-296 ms with 59-144 presses. Only `m`
    is slow; `s` at 296 ms is within 5% of the goal."""
    others = {  # letter: (recent median ms, presses)
        "e": (213, 144),
        "t": (231, 120),
        "a": (245, 110),
        "o": (252, 98),
        "i": (260, 90),
        "n": (268, 85),
        "r": (281, 72),
        "s": (296, 59),
    }
    timing = {ord(c): _timing(ms, presses=n, sessions=6) for c, (ms, n) in others.items()}
    timing[M] = _timing(354, presses=69, sessions=6)
    ctx = _ctx(timing)
    assert ctx.course.goal_ms == pytest.approx(290, abs=0.5)
    assert await _speed_keys(ctx) == [M]
