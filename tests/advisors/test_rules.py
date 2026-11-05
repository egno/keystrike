from __future__ import annotations

from dataclasses import replace

import pytest

from keystrike.advisors import rules
from keystrike.application.advisor_registry import AdvisorRegistry
from keystrike.domain.advice import (
    AdviceDigest,
    AdvisorContext,
    CourseState,
    Coverage,
    KeyTiming,
    Kind,
    Reason,
    RecentTally,
    validate_advice,
)
from keystrike.domain.enums import Finger, Hand
from keystrike.domain.keystroke_insights import Confusion, FingerErrors, KeystrokeInsights
from keystrike.domain.models import Keystroke, KeyTally

A, S, D, F, G = (ord(c) for c in "asdfg")
MS = 1_000_000
GOAL_MS = 300.0  # target_cpm 200


def _tally(errors: int, attempts: int, mean_ms: float = 250.0) -> KeyTally:
    samples = attempts - errors
    return KeyTally(
        samples=samples, time_ns=int(samples * mean_ms * MS), errors=errors, attempts=attempts
    )


def _timing(recent_median_ms: float, presses: int = 60, sessions: int = 4) -> KeyTiming:
    over = presses // 2 if recent_median_ms > GOAL_MS else presses // 5
    return KeyTiming(
        presses=presses,
        over_goal=over,
        tail=0,
        median_ms=recent_median_ms,
        recent_median_ms=recent_median_ms,
        sessions=sessions,
    )


def _ctx(
    tallies: dict[int, KeyTally],
    *,
    timing: dict[int, KeyTiming] | None = None,
    confidence: dict[int, float] | None = None,
    insights: KeystrokeInsights | None = None,
    keystrokes: dict[str, list[Keystroke]] | None = None,
    unlocked: tuple[int, ...] = (A, S, D, F, G),
    target_cpm: int = 200,  # 300 ms per key
) -> AdvisorContext:
    return AdvisorContext(
        layout="qwerty",
        sessions=(),
        course=CourseState(unlocked=unlocked, target_cpm=target_cpm, confidence=confidence or {}),
        digest=AdviceDigest(keys=tallies, timing=timing or {}),
        insights=insights or KeystrokeInsights(),
        keystrokes=keystrokes or {},
        coverage=Coverage(digest_sessions=10, stream_sessions=6),
    )


def _of(advice, kind: Kind, reason: Reason | None = None):
    return [
        r
        for r in advice.recommendations
        if r.kind is kind and (reason is None or r.reason is reason)
    ]


def _confusion(target: int, typed: int, count: int, **kwargs) -> Confusion:
    """A mistype that passes the contrast gates unless told otherwise."""
    kwargs.setdefault("sessions", 2)
    kwargs.setdefault("newest_half", 1)
    return Confusion(target, typed, count, **kwargs)


# --- focus ----------------------------------------------------------------------


async def test_focus_is_the_key_with_the_highest_shrunk_error_rate_and_carries_evidence():
    advice = await rules.rules_advisor(
        _ctx({A: _tally(1, 100), S: _tally(10, 40), D: _tally(1, 2)})
    )
    (focus,) = _of(advice, Kind.FOCUS)
    assert focus.keys == (S,)  # 10/43 beats 1/5 and 1/103
    assert focus.reason is Reason.ACCURACY
    assert (focus.evidence.events, focus.evidence.opportunities) == (10, 40)
    assert focus.evidence.sessions == 10


async def test_no_focus_when_no_key_is_bad_enough():
    advice = await rules.rules_advisor(_ctx({A: _tally(1, 200), S: _tally(0, 50)}))
    assert _of(advice, Kind.FOCUS) == []


async def test_the_advisor_never_writes_a_summary():
    """The core writes the summary from the validated recommendations."""
    insights = KeystrokeInsights(confusions=(_confusion(S, D, 4),))
    for ctx in (
        _ctx({S: _tally(10, 40)}, insights=insights),
        _ctx({A: _tally(0, 80)}),
        _ctx({}),
    ):
        assert (await rules.rules_advisor(ctx)).summary == ""


# --- contrast -------------------------------------------------------------------


async def test_a_repeated_mistype_is_a_contrast_with_its_evidence():
    insights = KeystrokeInsights(confusions=(_confusion(S, D, 4, sessions=3),))
    advice = await rules.rules_advisor(
        _ctx({A: _tally(0, 50), S: _tally(8, 70)}, insights=insights)
    )
    (contrast,) = _of(advice, Kind.CONTRAST)
    assert contrast.keys == (S, D)
    assert contrast.reason is Reason.CONFUSION
    assert (contrast.evidence.events, contrast.evidence.opportunities) == (4, 70)
    assert contrast.evidence.sessions == 6  # the raw streams cover fewer sessions
    assert contrast.evidence.event_sessions == 3


@pytest.mark.parametrize(
    "confusion",
    [
        Confusion(S, D, 2, sessions=2, newest_half=1),  # two events: too few
        Confusion(S, D, 5, sessions=1, newest_half=3),  # one session only
        Confusion(S, D, 5, sessions=3, newest_half=0),  # nothing in the newer half
    ],
    ids=["count", "sessions", "newest_half"],
)
async def test_a_mistype_must_pass_every_contrast_gate(confusion: Confusion):
    ctx = _ctx({S: _tally(8, 70)}, insights=KeystrokeInsights(confusions=(confusion,)))
    assert _of(await rules.rules_advisor(ctx), Kind.CONTRAST) == []


async def test_a_mistype_at_every_gate_is_a_contrast():
    confusion = Confusion(S, D, 3, sessions=2, newest_half=1)
    ctx = _ctx({S: _tally(8, 70)}, insights=KeystrokeInsights(confusions=(confusion,)))
    assert len(_of(await rules.rules_advisor(ctx), Kind.CONTRAST)) == 1


@pytest.mark.parametrize("count", [3, 5])
async def test_weak_evidence_gives_a_weak_effect_through_the_core(count: int):
    insights = KeystrokeInsights(confusions=(_confusion(S, D, count),))
    ctx = _ctx({S: _tally(3, 70)}, insights=insights)
    checked = validate_advice(await rules.rules_advisor(ctx), ctx.course)
    (contrast,) = checked.of_kind(Kind.CONTRAST)
    assert contrast.applied == pytest.approx(0.8 * min(1.0, count / 5))


async def test_recommendations_below_the_evidence_bar_are_not_returned():
    insights = KeystrokeInsights(confusions=(_confusion(S, D, 1),))  # one event
    advice = await rules.rules_advisor(_ctx({S: _tally(1, 5)}, insights=insights))
    assert advice.recommendations == ()


# --- speed (see also test_rules_timing.py) --------------------------------------


async def test_each_slow_key_is_its_own_speed_recommendation_slowest_first():
    tallies = {A: _tally(0, 60), S: _tally(0, 60), D: _tally(0, 60)}
    timing = {A: _timing(250), S: _timing(420), D: _timing(360)}
    advice = await rules.rules_advisor(_ctx(tallies, timing=timing))
    slow = _of(advice, Kind.EMPHASIZE, Reason.SPEED)
    assert [r.keys for r in slow] == [(S,), (D,)]
    assert slow[0].strength == pytest.approx(min(1.0, (420 / 300 - 1) / 0.5))
    assert slow[1].strength == pytest.approx((360 / 300 - 1) / 0.5)
    ev = slow[0].evidence
    assert (ev.events, ev.opportunities, ev.sessions) == (30, 60, 4)  # the key's own timing


async def test_no_speed_recommendation_without_a_goal():
    ctx = _ctx({S: _tally(0, 60)}, timing={S: _timing(900)}, target_cpm=0)
    assert _of(await rules.rules_advisor(ctx), Kind.EMPHASIZE, Reason.SPEED) == []


# --- weak finger ----------------------------------------------------------------


def _finger_stream() -> dict[str, list[Keystroke]]:
    ring = [Keystroke(cp, cp, 0, correct=True, finger=Finger.RING, hand=Hand.L) for cp in (S, D)]
    pinky = [Keystroke(A, A, 0, correct=True, finger=Finger.PINKY, hand=Hand.L)]
    return {"s1": (ring + pinky) * 3}


def _bad_ring() -> KeystrokeInsights:
    return KeystrokeInsights(
        fingers=(
            FingerErrors(Hand.L, Finger.RING, errors=15, attempts=50),
            FingerErrors(Hand.L, Finger.PINKY, errors=1, attempts=50),
            FingerErrors(Hand.L, Finger.INDEX, errors=1, attempts=50),
        )
    )


async def test_each_key_of_the_weak_finger_carries_its_own_evidence():
    tallies = {A: _tally(0, 50), S: _tally(9, 40), D: _tally(4, 30)}
    advice = await rules.rules_advisor(
        _ctx(tallies, insights=_bad_ring(), keystrokes=_finger_stream())
    )
    recs = _of(advice, Kind.EMPHASIZE, Reason.ACCURACY)
    assert [r.keys for r in recs] == [(S,), (D,)]  # worst first, one key each
    assert [(r.evidence.events, r.evidence.opportunities) for r in recs] == [(9, 40), (4, 30)]
    # The finger's pooled 15 of 50 is on no key.
    assert all((r.evidence.events, r.evidence.opportunities) != (15, 50) for r in recs)


async def test_a_key_of_the_weak_finger_under_the_evidence_floor_is_skipped():
    tallies = {A: _tally(0, 50), S: _tally(9, 40), D: _tally(1, 30)}  # d: one error only
    advice = await rules.rules_advisor(
        _ctx(tallies, insights=_bad_ring(), keystrokes=_finger_stream())
    )
    assert [r.keys for r in _of(advice, Kind.EMPHASIZE, Reason.ACCURACY)] == [(S,)]

    few_presses = {A: _tally(0, 50), S: _tally(9, 40), D: _tally(3, 8)}  # d: 8 presses
    advice = await rules.rules_advisor(
        _ctx(few_presses, insights=_bad_ring(), keystrokes=_finger_stream())
    )
    assert [r.keys for r in _of(advice, Kind.EMPHASIZE, Reason.ACCURACY)] == [(S,)]


async def test_the_worst_finger_is_emphasized_only_when_clearly_above_average():
    tallies = {A: _tally(0, 50), S: _tally(5, 50), D: _tally(0, 50)}
    even = KeystrokeInsights(
        fingers=(
            FingerErrors(Hand.L, Finger.RING, errors=5, attempts=50),
            FingerErrors(Hand.L, Finger.PINKY, errors=5, attempts=50),
        )
    )
    advice = await rules.rules_advisor(_ctx(tallies, insights=even, keystrokes=_finger_stream()))
    assert _of(advice, Kind.EMPHASIZE, Reason.ACCURACY) == []


# --- ease -----------------------------------------------------------------------


async def test_mastered_keys_are_eased_one_each_but_never_the_newest_or_a_slow_one():
    tallies = {
        A: _tally(0, 80),
        S: _tally(1, 80),
        D: _tally(0, 80),
        F: _tally(9, 30),
        G: _tally(0, 80),
    }
    timing = {A: _timing(250), S: _timing(260), D: _timing(270), F: _timing(250), G: _timing(400)}
    confidence = {A: 1.0, S: 1.0, D: 1.0, F: 0.3, G: 1.0}
    advice = await rules.rules_advisor(_ctx(tallies, timing=timing, confidence=confidence))
    eased = _of(advice, Kind.EASE)
    assert all(len(r.keys) == 1 and r.reason is Reason.MASTERED for r in eased)
    assert {r.keys[0] for r in eased} == {A, S, D}  # F is weak, G is slow and the newest
    (a,) = [r for r in eased if r.keys == (A,)]
    assert (a.evidence.events, a.evidence.opportunities) == (80, 80)  # a's own tally
    assert a.strength == rules.REST_STRENGTH

    newest_d = _ctx(tallies, timing=timing, confidence=confidence, unlocked=(A, S, G, F, D))
    assert (D,) not in [r.keys for r in _of(await rules.rules_advisor(newest_d), Kind.EASE)]


async def test_a_key_without_timing_is_never_eased():
    ctx = _ctx({A: _tally(0, 80)}, confidence={A: 1.0}, unlocked=(A, S))
    assert _of(await rules.rules_advisor(ctx), Kind.EASE) == []


@pytest.mark.parametrize(("presses", "sessions"), [(19, 4), (60, 1)])
async def test_a_key_with_too_little_timing_is_not_eased(presses: int, sessions: int):
    ctx = _ctx(
        {A: _tally(0, 80)},
        timing={A: _timing(250, presses=presses, sessions=sessions)},
        confidence={A: 1.0},
        unlocked=(A, S),
    )
    assert _of(await rules.rules_advisor(ctx), Kind.EASE) == []


async def test_a_key_with_a_few_errors_is_not_eased():
    ctx = _ctx({A: _tally(3, 100)}, timing={A: _timing(250)}, confidence={A: 1.0}, unlocked=(A, S))
    assert _of(await rules.rules_advisor(ctx), Kind.EASE) == []  # 3% is above the 2% limit


# --- the dead band: no flip-flopping --------------------------------------------


@pytest.mark.parametrize(
    ("median_ms", "emphasized", "eased"),
    [
        (250, False, True),  # clearly fast: 83% of the 300 ms goal
        (284, False, True),  # just under 95%: eased
        (291, False, False),  # 97%: dead band
        (299, False, False),
        (310, False, False),  # 103%: within the slow margin
        (314, False, False),  # just under 105%: not slow
        (330, True, False),  # clearly slow
    ],
)
async def test_a_key_about_at_the_goal_is_neither_emphasized_nor_eased(
    median_ms: float, emphasized: bool, eased: bool
):
    tallies = {A: _tally(0, 80), S: _tally(0, 80), D: _tally(0, 80)}
    timing = {A: _timing(median_ms), S: _timing(250), D: _timing(250)}
    confidence = {A: 1.0, S: 1.0, D: 1.0}
    advice = await rules.rules_advisor(
        _ctx(tallies, timing=timing, confidence=confidence, unlocked=(A, S, D))
    )
    assert any(r.keys == (A,) for r in _of(advice, Kind.EMPHASIZE, Reason.SPEED)) is emphasized
    assert any(r.keys == (A,) for r in _of(advice, Kind.EASE)) is eased


async def test_the_session_to_session_wobble_around_the_goal_changes_nothing():
    """The same key at 98%, 100% and 102% of the goal gets no advice either way."""
    for median_ms in (294, 300, 306):
        tallies = {A: _tally(0, 80), S: _tally(0, 80), D: _tally(0, 80)}
        timing = {A: _timing(median_ms), S: _timing(250), D: _timing(250)}
        confidence = {A: 1.0, S: 1.0, D: 1.0}
        advice = await rules.rules_advisor(
            _ctx(tallies, timing=timing, confidence=confidence, unlocked=(A, S, D))
        )
        for rec in advice.recommendations:
            assert A not in rec.keys


# --- through the core -----------------------------------------------------------


async def test_rich_output_survives_core_validation_with_one_key_per_list_item():
    insights = KeystrokeInsights(confusions=(_confusion(S, D, 5),))
    ctx = _ctx(
        {
            A: _tally(0, 80),
            S: _tally(10, 40),
            D: _tally(0, 60),
            F: _tally(0, 60),
            G: _tally(2, 60),
        },
        timing={A: _timing(250), S: _timing(420), D: _timing(250), F: _timing(400)},
        confidence={A: 1.0, S: 0.3, D: 1.0, F: 0.5, G: 0.5},
        insights=insights,
    )
    advice = await rules.rules_advisor(ctx)
    assert {r.kind for r in advice.recommendations} >= {
        Kind.FOCUS,
        Kind.CONTRAST,
        Kind.EMPHASIZE,
        Kind.EASE,
    }
    checked = validate_advice(advice, ctx.course)
    kept = checked.recommendations
    assert next(r.keys for r in kept if r.kind is Kind.FOCUS) == (S,)
    assert next(r.keys for r in kept if r.kind is Kind.CONTRAST) == (S, D)
    lists = [r for r in kept if r.kind in (Kind.EMPHASIZE, Kind.EASE)]
    assert lists
    assert all(len(r.keys) == 1 for r in lists)
    # five unlocked keys: the budget is ceil(5 / 3) = 2 keys per kind
    assert len([r for r in lists if r.kind is Kind.EASE]) <= 2
    assert len([r for r in lists if r.kind is Kind.EMPHASIZE]) <= 2
    assert validate_advice(checked, ctx.course) == checked


def test_spec_is_local_and_registers_like_a_plugin():
    registry = AdvisorRegistry()
    rules.register(registry)
    spec = registry.get("rules")
    assert spec.name == "rules"
    assert spec.capabilities.needs_keystrokes
    assert not spec.capabilities.sends_data_off_device
    assert spec.create({}) is rules.rules_advisor


# --- recency --------------------------------------------------------------------


def _recent_ctx(
    tallies: dict[int, KeyTally],
    recent: dict[int, RecentTally],
    **kwargs,
) -> AdvisorContext:
    base = _ctx(tallies, **kwargs)
    return replace(base, digest=replace(base.digest, recent=recent))


def _weighted(t: KeyTally, weight: float) -> RecentTally:
    return RecentTally(
        t.samples * weight, t.time_ns * weight, t.errors * weight, t.attempts * weight
    )


async def test_a_key_that_is_failing_now_is_the_focus_over_one_that_failed_long_ago():
    """Equal exact counts. s failed long ago (low weight), d fails now (full weight)."""
    s_tally, d_tally = _tally(10, 40), _tally(10, 40)
    ctx = _recent_ctx(
        {S: s_tally, D: d_tally},
        {S: _weighted(s_tally, 0.2), D: _weighted(d_tally, 1.0)},
    )
    (focus,) = _of(await rules.rules_advisor(ctx), Kind.FOCUS)
    assert focus.keys == (D,)
    assert (focus.evidence.events, focus.evidence.opportunities) == (10, 40)  # exact


async def test_an_old_error_burst_fades_once_recent_sessions_are_clean():
    """10 errors in 80 presses overall (12.5%: a focus with equal weights). But 10 of
    them were in old sessions; the recent sessions are clean."""
    exact = _tally(10, 80)
    old = RecentTally(
        samples=30 * 0.2, time_ns=30 * 0.2 * 250e6, errors=10 * 0.2, attempts=40 * 0.2
    )
    clean = RecentTally(samples=40.0, time_ns=40 * 250e6, errors=0.0, attempts=40.0)
    faded = RecentTally(*(a + b for a, b in zip(old, clean, strict=True)))
    assert _of(await rules.rules_advisor(_ctx({S: exact})), Kind.FOCUS)  # equal weights: a focus
    ctx = _recent_ctx({S: exact}, {S: faded})
    assert _of(await rules.rules_advisor(ctx), Kind.FOCUS) == []  # 2/48 recent: under 8%


async def test_contrast_strength_scales_with_recency_but_keeps_its_evidence():
    fresh = _confusion(S, D, 4, recent_count=4.0)
    faded = _confusion(S, D, 4, recent_count=1.0)
    strengths = []
    for confusion in (fresh, faded):
        ctx = _ctx({S: _tally(8, 70)}, insights=KeystrokeInsights(confusions=(confusion,)))
        (contrast,) = _of(await rules.rules_advisor(ctx), Kind.CONTRAST)
        assert contrast.evidence.events == 4  # the evidence is the exact count either way
        strengths.append(contrast.strength)
    assert strengths[0] == pytest.approx(0.8)
    assert strengths[1] == pytest.approx(0.8 * 0.25)


async def test_a_recent_error_stops_a_mastered_key_from_being_eased():
    tally = _tally(0, 80)  # the exact counts look perfect
    recent = RecentTally(samples=76.0, time_ns=76 * 250e6, errors=4.0, attempts=80.0)  # but 5% now
    ctx = _recent_ctx(
        {A: tally, S: tally, D: tally},
        {A: _weighted(tally, 1.0), S: recent, D: _weighted(tally, 1.0)},
        timing={A: _timing(250), S: _timing(250), D: _timing(250)},
        confidence={A: 1.0, S: 1.0, D: 1.0},
        unlocked=(A, S, D),
    )
    eased = [r.keys for r in _of(await rules.rules_advisor(ctx), Kind.EASE)]
    assert (A,) in eased
    assert (S,) not in eased


async def test_the_worst_finger_follows_the_recent_rate():
    tallies = {A: _tally(3, 50), S: _tally(5, 50), D: _tally(4, 50)}
    insights = KeystrokeInsights(
        fingers=(
            # the ring finger has the most errors overall, but they are old
            FingerErrors(
                Hand.L, Finger.RING, errors=15, attempts=50, recent_errors=1.5, recent_attempts=40.0
            ),
            FingerErrors(
                Hand.L, Finger.PINKY, errors=6, attempts=50, recent_errors=6.0, recent_attempts=40.0
            ),
            FingerErrors(
                Hand.L, Finger.INDEX, errors=1, attempts=50, recent_errors=0.5, recent_attempts=40.0
            ),
        )
    )
    ctx = _ctx(tallies, insights=insights, keystrokes=_finger_stream())
    (finger,) = _of(await rules.rules_advisor(ctx), Kind.EMPHASIZE, Reason.ACCURACY)
    assert finger.keys == (A,)  # the pinky is the worst finger now
    assert (finger.evidence.events, finger.evidence.opportunities) == (3, 50)  # a's own


async def test_a_context_without_recency_information_weighs_every_session_the_same():
    """A plain digest (no `recent`) gives the same advice as one with equal weights."""
    tallies = {A: _tally(1, 100), S: _tally(10, 40)}
    plain = await rules.rules_advisor(_ctx(tallies))
    equal = await rules.rules_advisor(
        _recent_ctx(tallies, {cp: _weighted(t, 1.0) for cp, t in tallies.items()})
    )
    assert plain == equal
