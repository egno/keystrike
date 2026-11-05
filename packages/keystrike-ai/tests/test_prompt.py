from __future__ import annotations

from dataclasses import replace

import pytest

from keystrike.domain.advice import validate_advice
from keystrike.domain.keystroke_insights import Confusion, FingerErrors
from keystrike.plugin_api import (
    AdviceDigest,
    AdvisorContext,
    Bigram,
    CourseState,
    Coverage,
    Finger,
    Hand,
    KeystrokeInsights,
    KeyTally,
    KeyTiming,
    Kind,
    Reason,
)
from keystrike_ai.prompt import RESPONSE_SCHEMA, build_user_prompt, parse_response

A, S, T, H, D, Z = (ord(c) for c in "asthdz")
KNOWN = frozenset({A, S, T, H})


def _ctx(
    keys: dict[int, KeyTally] | None = None,
    insights: KeystrokeInsights | None = None,
    timing: dict[int, KeyTiming] | None = None,
) -> AdvisorContext:
    return AdvisorContext(
        layout="qwerty",
        sessions=(),
        course=CourseState(unlocked=(A, S, D, Z), target_cpm=300, confidence={A: 0.9, S: 0.4}),
        digest=AdviceDigest(
            keys=keys
            or {
                A: KeyTally(samples=4, time_ns=800_000_000, errors=0, attempts=4),
                S: KeyTally(samples=3, time_ns=900_000_000, errors=3, attempts=6),
            },
            pairs={Bigram(A, S): KeyTally(samples=2, time_ns=1, errors=2, attempts=4)},
            timing=timing or {},
        ),
        insights=insights or KeystrokeInsights(),
        coverage=Coverage(digest_sessions=4, stream_sessions=2),
    )


def _kinds(advice):
    return [(r.kind, r.keys, r.reason) for r in advice.recommendations]


def test_parse_valid_reply_becomes_recommendations_with_evidence_from_the_digest():
    reply = (
        '{"summary": " Slow on s. ", "focus_key": "s", "focus_pair": "as",'
        ' "rest_keys": ["a"], "emphasis_keys": ["s", "d"]}'
    )
    advice = parse_response(reply, _ctx())
    assert advice.summary == "Slow on s."
    assert not advice.failed
    assert _kinds(advice) == [
        (Kind.FOCUS_PAIR, (A, S), Reason.ACCURACY),
        (Kind.FOCUS, (S,), Reason.ACCURACY),
        (Kind.EMPHASIZE, (S,), Reason.ACCURACY),
        (Kind.EASE, (A,), Reason.MASTERED),
    ]  # d is unlocked but has no tally, so it is not a known key
    focus_key = advice.of_kind(Kind.FOCUS)[0]
    assert (focus_key.evidence.events, focus_key.evidence.opportunities) == (3, 6)  # from the tally
    assert focus_key.evidence.sessions == 4
    pair = advice.of_kind(Kind.FOCUS_PAIR)[0]
    assert (pair.evidence.events, pair.evidence.opportunities) == (2, 4)
    ease = advice.of_kind(Kind.EASE)[0]
    assert (ease.evidence.events, ease.evidence.opportunities) == (4, 4)  # correct presses


def test_rest_keys_become_one_ease_each_with_the_key_s_own_evidence():
    keys = {
        A: KeyTally(samples=4, time_ns=1, errors=0, attempts=4),
        S: KeyTally(samples=9, time_ns=1, errors=1, attempts=10),
    }
    advice = parse_response('{"summary": "Mine.", "rest_keys": ["a", "s"]}', _ctx(keys))
    eases = advice.of_kind(Kind.EASE)
    assert [r.keys for r in eases] == [(A,), (S,)]
    assert [(r.evidence.events, r.evidence.opportunities) for r in eases] == [(4, 4), (9, 10)]
    assert advice.summary == "Mine."  # the model's own text stays


def test_the_model_s_summary_survives_validation():
    advice = parse_response('{"summary": "Watch the s.", "focus_key": "s"}', _ctx())
    course = CourseState(unlocked=(A, S), target_cpm=300, confidence={})
    assert validate_advice(advice, course).summary == "Watch the s."


def test_the_model_cannot_claim_its_own_evidence_or_strength():
    advice = parse_response('{"focus_key": "s", "evidence": [99, 99]}', _ctx())
    assert advice.recommendations[0].evidence.events == 3


def _timing(presses: int = 40, median: float = 300.0, sessions: int = 3) -> KeyTiming:
    return KeyTiming(
        presses=presses,
        over_goal=presses // 2,
        tail=2,
        median_ms=median,
        recent_median_ms=median,
        sessions=sessions,
    )


def _speed_reasons(timing: dict[int, KeyTiming]) -> dict[tuple[int, ...], Reason]:
    advice = parse_response('{"emphasis_keys": ["a", "s"]}', _ctx(timing=timing))
    return {r.keys: r.reason for r in advice.recommendations}


def test_a_slow_emphasis_key_is_a_speed_recommendation_judged_on_the_median():
    # 300 CPM goal = 200 ms. `a` is slow (median 300 ms); `s` is at the goal.
    timing = {A: _timing(median=300.0), S: _timing(median=200.0)}
    advice = parse_response('{"emphasis_keys": ["a", "s"]}', _ctx(timing=timing))
    reasons = {r.keys: r.reason for r in advice.recommendations}
    assert reasons == {(A,): Reason.SPEED, (S,): Reason.ACCURACY}
    speed = advice.of_kind(Kind.EMPHASIZE)[0]
    assert (speed.evidence.events, speed.evidence.opportunities) == (
        20,
        40,
    )  # slow presses of clean presses
    assert speed.evidence.sessions == 3


def test_a_high_mean_with_a_median_at_the_goal_is_not_a_speed_recommendation():
    """A few long pauses pull the mean up. The median says the key is at the goal."""
    keys = {
        A: KeyTally(samples=40, time_ns=40 * 450_000_000, errors=3, attempts=43),  # mean 450 ms
        S: KeyTally(samples=40, time_ns=40 * 100_000_000, errors=0, attempts=40),
    }
    ctx = _ctx(keys, timing={A: _timing(median=205.0), S: _timing(median=200.0)})
    advice = parse_response('{"emphasis_keys": ["a"]}', ctx)
    assert advice.recommendations[0].reason is Reason.ACCURACY


def test_too_few_presses_or_sessions_or_no_timing_is_not_a_speed_recommendation():
    for timing in (
        {A: _timing(presses=19, median=400.0)},  # too few presses
        {A: _timing(sessions=1, median=400.0)},  # one session only
        {},  # no timing at all: no guess from the mean
    ):
        assert _speed_reasons(timing).get((A,)) is Reason.ACCURACY


def test_the_dead_band_around_the_goal_is_not_slow():
    assert _speed_reasons({A: _timing(median=209.0)})[(A,)] is Reason.ACCURACY  # 104.5% of 200
    assert _speed_reasons({A: _timing(median=211.0)})[(A,)] is Reason.SPEED  # 105.5%


def test_the_prompt_shows_speed_per_key_from_clean_presses():
    user = build_user_prompt(_ctx(timing={A: _timing(median=300.0), S: _timing(median=200.0)}))
    assert "Speed per key (median of clean presses; goal 200 ms;" in user
    assert "- 'a': median 300 ms, 20 of 40 over the goal" in user
    assert user.index("'a': median 300") < user.index("'s': median 200")  # slowest first


def test_without_timing_the_prompt_has_no_speed_block():
    assert "Speed per key" not in build_user_prompt(_ctx())


def test_parse_tolerates_fences_and_chatter():
    reply = 'Sure!\n```json\n{"summary": "ok", "focus_key": "a"}\n```\nHope that helps.'
    assert parse_response(reply, _ctx()).of_kind(Kind.FOCUS)[0].keys == (A,)


def test_parse_pair_as_list():
    ctx = _ctx({A: KeyTally(1, 1, 0, 1), S: KeyTally(1, 1, 0, 1), T: KeyTally(1, 1, 0, 1)})
    assert parse_response('{"focus_pair": ["a", "t"]}', ctx).of_kind(Kind.FOCUS_PAIR)[0].keys == (
        A,
        T,
    )


def test_parse_drops_unknown_or_malformed_fields_but_keeps_the_rest():
    reply = (
        '{"summary": 5, "focus_key": 115, "focus_pair": "aa",'
        ' "rest_keys": "abc", "emphasis_keys": ["z", "s", "s", 7, "ab"]}'
    )
    advice = parse_response(reply, _ctx())
    assert advice.summary == ""
    assert _kinds(advice) == [(Kind.EMPHASIZE, (S,), Reason.ACCURACY)]
    # integers are not accepted for the focus, "aa" is one key twice, "z" is unknown


def test_parse_caps_list_length():
    keys = {ord(c): KeyTally(3, 3, 3, 6) for c in "abcdefghij"}
    reply = '{"emphasis_keys": ["a","b","c","d","e","f","g"]}'
    assert len(parse_response(reply, _ctx(keys)).of_kind(Kind.EMPHASIZE)) == 5


@pytest.mark.parametrize("reply", ["", "no json here", "[1, 2]", '{"summary": ', "null"])
def test_parse_rejects_non_object_replies(reply: str):
    with pytest.raises(ValueError):  # noqa: PT011 - JSONDecodeError is a ValueError
        parse_response(reply, _ctx())


def test_what_the_core_does_with_the_parsed_advice():
    """A key the model lists without errors has no evidence and is dropped."""
    keys = {
        A: KeyTally(samples=40, time_ns=40 * 100_000_000, errors=0, attempts=40),
        S: KeyTally(samples=30, time_ns=30 * 100_000_000, errors=6, attempts=36),
    }
    ctx = _ctx(keys)
    advice = parse_response('{"emphasis_keys": ["a", "s"]}', ctx)
    checked = validate_advice(advice, ctx.course)
    assert [r.keys for r in checked.recommendations] == [(S,)]  # a: 0 errors, s: 6 errors


def test_schema_requires_every_field():
    assert set(RESPONSE_SCHEMA["required"]) == set(RESPONSE_SCHEMA["properties"])


def test_prompt_describes_the_course_and_the_digest():
    user = build_user_prompt(_ctx())
    assert "Goal: 300 CPM (200 ms per key)." in user
    assert "Unlocked keys, in learning order: a s d z" in user
    assert "Newest key (being learned now): z" in user
    assert "'s': 50% errors (3/6), 300 ms, confidence 0.40" in user
    assert "'as': 2 errors / 4 attempts" in user
    assert "' '" not in user


def test_keys_rank_by_error_rate_not_raw_error_count():
    keys = {
        A: KeyTally(samples=90, time_ns=90_000_000, errors=5, attempts=100),  # 5%
        S: KeyTally(samples=5, time_ns=5_000_000, errors=4, attempts=9),  # 44%
    }
    user = build_user_prompt(_ctx(keys))
    assert user.index("'s':") < user.index("'a':")


def test_prompt_includes_mistypes_and_finger_errors():
    insights = KeystrokeInsights(
        confusions=(Confusion(S, D, 2),),
        fingers=(FingerErrors(Hand.L, Finger.RING, errors=2, attempts=4),),
    )
    user = build_user_prompt(replace(_ctx(), insights=insights))
    assert "'s' typed as 'd': 2 times" in user
    assert "left ring finger: 50% (2/4)" in user
