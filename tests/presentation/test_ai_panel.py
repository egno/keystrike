from __future__ import annotations

from keystrike.domain.ai_models import AiAnalysis
from keystrike.domain.models import Bigram
from keystrike.presentation.widgets.ai_panel import build_lines


def test_full_analysis_lines():
    analysis = AiAnalysis(
        summary="Work on s.",
        focus_pair=Bigram(ord("a"), ord("s")),
        emphasis_keys=(ord("s"), ord("d")),
        rest_keys=(ord("a"),),
    )
    assert build_lines(analysis) == [
        "Work on s.",
        "Focus: a → s",
        "Practice more: s, d",
        "Ease up on: a",
    ]


def test_focus_key_without_pair():
    assert build_lines(AiAnalysis(focus_key=ord("e"))) == ["Focus: e"]


def test_unprintable_codepoints_use_hex():
    assert build_lines(AiAnalysis(emphasis_keys=(0x7,)))[0] == "Practice more: U+0007"


def test_failure_shows_only_the_error():
    assert build_lines(AiAnalysis(error="AI analysis unavailable (TimeoutError)")) == [
        "AI analysis unavailable (TimeoutError)"
    ]


def test_empty_analysis_has_no_lines():
    assert build_lines(AiAnalysis()) == []


def test_failure_with_previous_advice_keeps_showing_it():
    previous = AiAnalysis(summary="Work on s.", focus_key=ord("s"))
    lines = build_lines(
        AiAnalysis(error="AI analysis unavailable (TimeoutError)"), previous=previous
    )
    assert lines == [
        "AI analysis unavailable (TimeoutError) — keeping the previous advice:",
        "Work on s.",
        "Focus: s",
    ]
