from __future__ import annotations

from keystrike.domain.advice import CourseState, Kind, LessonAdvice, Reason, validate_advice
from keystrike.presentation.widgets.advice_panel import build_lines
from tests.advice_helpers import advice, rec

A, S, E = ord("a"), ord("s"), ord("e")


def test_every_recommendation_shows_what_why_and_the_evidence():
    full = advice(
        rec(Kind.FOCUS, S, events=3, opportunities=40),
        rec(Kind.FOCUS_PAIR, A, S),
        rec(Kind.EMPHASIZE, ord(" "), reason=Reason.SPEED, events=12, opportunities=30),
        rec(Kind.EASE, A, events=60, opportunities=60),
        rec(Kind.CONTRAST, E, ord("i"), events=2, opportunities=70),
        summary="Slow on s",
    )
    assert build_lines(full) == [
        "Slow on s",
        "Focus: s (accuracy, 3 of 40)",
        "Focus: a → s (accuracy, 5 of 50)",
        "Practice more: U+0020 (speed, 12 of 30)",
        "Ease up on: a (mastered, 60 of 60)",
        "Tell apart: e / i (confusion, 2 of 70)",
    ]


def test_validated_advice_shows_the_core_summary_and_one_line_per_key():
    course = CourseState(unlocked=(A, S, E), target_cpm=200, confidence={A: 1.0, S: 1.0, E: 1.0})
    raw = advice(
        rec(Kind.EMPHASIZE, S, reason=Reason.SPEED, events=12, opportunities=30),
        rec(Kind.EASE, A, events=60, opportunities=60),
    )
    assert build_lines(validate_advice(raw, course)) == [
        "s is slower than your goal — it gets extra practice.",
        "Practice more: s (speed, 12 of 30)",
        "Ease up on: a (mastered, 60 of 60)",
    ]


def test_a_recommendation_without_evidence_shows_only_the_reason():
    assert build_lines(advice(rec(Kind.FOCUS, S, events=0, opportunities=0))) == [
        "Focus: s (accuracy)"
    ]


def test_failure_shows_the_previous_advice_that_stays_in_effect():
    failed = LessonAdvice(source="llm", error="LLM unavailable (OSError)")
    good = advice(rec(Kind.FOCUS, S, events=3, opportunities=20), summary="ok")
    assert build_lines(failed) == ["LLM unavailable (OSError)"]
    assert build_lines(failed, previous=good) == [
        "LLM unavailable (OSError) — keeping the previous advice:",
        "ok",
        "Focus: s (accuracy, 3 of 20)",
    ]


def test_the_advisor_is_named_on_the_first_line():
    lines = build_lines(
        advice(rec(Kind.FOCUS, S, events=3, opportunities=20)), advisor="Rules (local)"
    )
    assert lines == ["Advisor: Rules (local)", "Focus: s (accuracy, 3 of 20)"]


def test_the_advisor_is_named_above_a_failure_too():
    failed = LessonAdvice(source="llm", error="LLM unavailable (OSError)")
    assert build_lines(failed, advisor="LLM") == ["Advisor: LLM", "LLM unavailable (OSError)"]
    good = advice(rec(Kind.FOCUS, S, events=3, opportunities=20))
    assert build_lines(failed, previous=good, advisor="LLM")[:2] == [
        "Advisor: LLM",
        "LLM unavailable (OSError) — keeping the previous advice:",
    ]


def test_without_an_advisor_there_is_no_header_line():
    assert build_lines(advice(rec(Kind.FOCUS, S)))[0].startswith("Focus")
