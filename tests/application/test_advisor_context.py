from __future__ import annotations

from dataclasses import replace

from keystrike.advisors.rules import rules_advisor
from keystrike.application.advisor_context import build_advisor_context, sample_context
from keystrike.domain.advice import Kind, Reason, neighbors, validate_advice
from keystrike.domain.enums import Mode
from keystrike.domain.models import Keystroke, KeyTally, SessionResult, SessionStats
from keystrike.infrastructure.layout_repo import BUNDLED_LAYOUTS

A, S = ord("a"), ord("s")


def _session(sid: str) -> SessionResult:
    return SessionResult(
        schema_version=5,
        session_id=sid,
        started_at=1.0,
        duration_ns=1,
        layout="qwerty",
        mode=Mode.ADAPTIVE,
        lesson_alphabet=(A,),
        focus_key=A,
        total_keystrokes=1,
        correct_keystrokes=1,
        unlocked_keys=(A, S),
    )


def test_coverage_counts_the_sessions_behind_each_part():
    sessions = [_session(f"s{i}") for i in range(10)]
    streams = {f"s{i}": [Keystroke(A, A, 0, correct=True)] for i in range(6)}
    ctx = build_advisor_context("qwerty", sessions, streams)
    assert (ctx.coverage.digest_sessions, ctx.coverage.stream_sessions) == (10, 6)


def test_no_streams_means_no_stream_coverage_and_no_insights():
    ctx = build_advisor_context("qwerty", [_session("s1")], {})
    assert ctx.coverage.stream_sessions == 0
    assert ctx.insights.is_empty


def test_layout_keys_are_passed_through_for_neighbour_checks():
    layout = BUNDLED_LAYOUTS["qwerty"]
    ctx = build_advisor_context("qwerty", [_session("s1")], {}, layout.keys)
    assert neighbors(ctx.layout_keys, ord("s")) == tuple(
        sorted(ord(c) for c in "qweadzxc")  # the keys around s on the left hand
    )


def test_sample_context_has_a_digest_for_every_unlocked_key():
    ctx = sample_context()
    assert set(ctx.course.unlocked) == set(ctx.digest.keys)
    assert ctx.coverage.digest_sessions == 3
    assert set(ctx.digest.timing) == set(ctx.digest.keys)  # speed advice can be tried with Ctrl+T


async def test_the_sample_context_gives_the_rules_advisor_something_to_say_about_speed():
    ctx = sample_context()
    checked = validate_advice(await rules_advisor(ctx), ctx.course)
    speed = [r for r in checked.recommendations if r.reason is Reason.SPEED]
    assert {r.keys for r in speed} == {(ord("n"),), (ord("o"),)}  # slower than the 343 ms goal
    assert all(r.kind is Kind.EMPHASIZE for r in speed)
    assert checked.summary  # the core renders it


def _tallied(sid: str, errors: int, attempts: int = 10) -> SessionResult:
    tally = KeyTally(
        samples=attempts - errors,
        time_ns=(attempts - errors) * 100_000_000,
        errors=errors,
        attempts=attempts,
    )
    return replace(_session(sid), stats=SessionStats(keys={A: tally}))


def test_the_digest_keeps_exact_counts_and_adds_recency_weighted_ones():
    sessions = [_tallied("new", errors=0), _tallied("mid", errors=4), _tallied("old", errors=4)]
    ctx = build_advisor_context("qwerty", sessions, {}, recency_decay=0.5)
    exact = ctx.digest.keys[A]
    assert (exact.errors, exact.attempts) == (8, 30)  # the evidence is never decayed
    recent = ctx.digest.recent[A]
    assert recent.attempts == 10 * (1.0 + 0.5 + 0.25)
    assert recent.errors == 4 * 0.5 + 4 * 0.25
    assert recent.error_rate < exact.errors / exact.attempts  # the errors are old
    assert ctx.session_weights == (1.0, 0.5, 0.25)


def test_a_decay_of_one_weighs_every_session_the_same():
    sessions = [_tallied("a", errors=1), _tallied("b", errors=3)]
    ctx = build_advisor_context("qwerty", sessions, {}, recency_decay=1.0)
    recent = ctx.digest.recent[A]
    assert (recent.errors, recent.attempts) == (4.0, 20.0)
    assert ctx.session_weights == (1.0, 1.0)


def test_insights_are_weighted_by_the_session_each_stream_belongs_to():
    wrong = [Keystroke(A, S, 0, correct=False), Keystroke(A, A, 1, correct=True)] * 2
    sessions = [_tallied("new", errors=0), _tallied("old", errors=0)]
    streams = {"new": [], "old": wrong}
    ctx = build_advisor_context("qwerty", sessions, streams, recency_decay=0.5)
    (confusion,) = ctx.insights.confusions
    assert confusion.count == 2
    assert confusion.recent_count == 1.0  # both mistypes are in the older session: 2 * 0.5


def _timed(*targets: str, step_ms: int = 300) -> list[Keystroke]:
    return [
        Keystroke(ord(c), ord(c), i * step_ms * 1_000_000, correct=True)
        for i, c in enumerate(targets)
    ]


def test_streams_give_timing_for_the_unlocked_keys_and_the_space():
    sessions = [replace(_session("new"), target_speed_cpm=300), _session("old")]
    streams = {"new": _timed("s", "a", "s", " ", "q", "a"), "old": _timed("a", "s", "a")}
    ctx = build_advisor_context("qwerty", sessions, streams, recency_decay=0.5)
    assert set(ctx.digest.timing) == {A, S}  # q is locked
    a = ctx.digest.timing[A]
    assert (a.presses, a.sessions) == (3, 2)  # the a after q counts; a first press does not
    assert a.over_goal == 3  # 300 ms against a 200 ms goal (300 CPM)
    assert ctx.digest.space is not None
    assert ctx.digest.space.presses == 1


def test_timing_uses_the_session_weights_by_session_id():
    sessions = [replace(_session("new"), target_speed_cpm=300), _session("old")]
    streams = {"old": _timed("s", "a", "s", "a", step_ms=100), "new": _timed("s", "a", "s")}
    ctx = build_advisor_context("qwerty", sessions, streams, recency_decay=0.1)
    a = ctx.digest.timing[A]
    assert a.median_ms == 100.0  # two old intervals, one new
    assert a.recent_median_ms == 300.0  # the new session weighs ten times more


def test_no_streams_means_no_timing():
    ctx = build_advisor_context("qwerty", [_session("s1")], {})
    assert ctx.digest.timing == {}
    assert ctx.digest.space is None
