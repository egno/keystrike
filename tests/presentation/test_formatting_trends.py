from __future__ import annotations

from keystrike.domain.enums import Mode
from keystrike.domain.models import SessionResult
from keystrike.presentation.formatting.trends import (
    focus_confidence_sparkline,
    format_aggregate_metric_trend_block,
    format_focus_confidence_trend_line,
    format_key_confidence_trend_line,
    format_key_metric_trend_block,
    format_key_speed_trend_line,
    format_wpm_trend_line,
    key_confidence_sparkline,
    key_confidence_values,
    wpm_sparkline,
)


def test_focus_confidence_sparkline_uses_focus_key_per_session():
    headers = [
        SessionResult(
            schema_version=3,
            session_id="s1",
            started_at=1.0,
            duration_ns=60_000_000_000,
            layout="qwerty",
            mode=Mode.ADAPTIVE,
            lesson_alphabet=(),
            focus_key=ord("a"),
            total_keystrokes=50,
            correct_keystrokes=50,
            key_confidence={ord("a"): 0.5, ord("b"): 1.0},
        ),
        SessionResult(
            schema_version=3,
            session_id="s2",
            started_at=2.0,
            duration_ns=30_000_000_000,
            layout="qwerty",
            mode=Mode.ADAPTIVE,
            lesson_alphabet=(),
            focus_key=ord("b"),
            total_keystrokes=50,
            correct_keystrokes=50,
            key_confidence={ord("a"): 0.5, ord("b"): 1.0},
        ),
    ]
    spark = focus_confidence_sparkline(headers)
    assert len(spark) == 2
    assert spark[0] <= spark[1]  # 0.5 then 1.0


def test_format_focus_confidence_trend_line_tracks_labeled_key():
    headers = [
        SessionResult(
            schema_version=3,
            session_id="s1",
            started_at=1.0,
            duration_ns=60_000_000_000,
            layout="qwerty",
            mode=Mode.ADAPTIVE,
            lesson_alphabet=(),
            focus_key=ord("a"),
            total_keystrokes=50,
            correct_keystrokes=50,
            key_confidence={ord("a"): 0.5, ord("b"): 1.0},
        ),
        SessionResult(
            schema_version=3,
            session_id="s2",
            started_at=2.0,
            duration_ns=30_000_000_000,
            layout="qwerty",
            mode=Mode.ADAPTIVE,
            lesson_alphabet=(),
            focus_key=ord("b"),
            total_keystrokes=50,
            correct_keystrokes=50,
            key_confidence={ord("a"): 0.5, ord("b"): 1.0},
        ),
    ]
    focus_line = format_focus_confidence_trend_line(headers)
    key_line = format_key_metric_trend_block(
        title="'b'",
        headers=headers,
        codepoint=ord("b"),
        speed_values=[],
        accuracy_values=[],
        limit=20,
    )
    assert focus_line == key_line.replace("[bold]'b'[/]", "[bold]Focus 'b'[/]", 1)


def test_format_focus_confidence_trend_line_includes_label_and_peak():
    headers = [
        SessionResult(
            schema_version=3,
            session_id="s1",
            started_at=1.0,
            duration_ns=60_000_000_000,
            layout="qwerty",
            mode=Mode.ADAPTIVE,
            lesson_alphabet=(),
            focus_key=ord("e"),
            total_keystrokes=50,
            correct_keystrokes=50,
            key_confidence={ord("e"): 0.75},
        ),
    ]
    line = format_focus_confidence_trend_line(headers)
    assert line.startswith("[bold]Focus 'e'[/] (1 sessions)")
    assert "[bold cyan]confidence[/]" in line
    assert "latest     0.75" in line
    assert "peak     0.75" in line


def test_focus_confidence_missing_key_defaults_zero():
    headers = [
        SessionResult(
            schema_version=3,
            session_id="s1",
            started_at=1.0,
            duration_ns=60_000_000_000,
            layout="qwerty",
            mode=Mode.ADAPTIVE,
            lesson_alphabet=(),
            focus_key=ord("z"),
            total_keystrokes=50,
            correct_keystrokes=50,
            key_confidence={},
        ),
    ]
    spark = focus_confidence_sparkline(headers)
    assert len(spark) == 1
    assert spark[0] == "▁"


def test_key_confidence_values_tracks_codepoint_across_sessions():
    headers = [
        SessionResult(
            schema_version=3,
            session_id="s1",
            started_at=1.0,
            duration_ns=60_000_000_000,
            layout="qwerty",
            mode=Mode.ADAPTIVE,
            lesson_alphabet=(),
            focus_key=ord("a"),
            total_keystrokes=50,
            correct_keystrokes=50,
            key_confidence={ord("e"): 0.4, ord("a"): 0.5},
        ),
        SessionResult(
            schema_version=3,
            session_id="s2",
            started_at=2.0,
            duration_ns=30_000_000_000,
            layout="qwerty",
            mode=Mode.ADAPTIVE,
            lesson_alphabet=(),
            focus_key=ord("e"),
            total_keystrokes=50,
            correct_keystrokes=50,
            key_confidence={ord("e"): 0.9, ord("a"): 0.5},
        ),
    ]
    values = key_confidence_values(headers, ord("e"))
    assert values == [0.4, 0.9]
    spark = key_confidence_sparkline(headers, ord("e"))
    assert len(spark) == 2
    assert spark[0] <= spark[1]


def test_key_confidence_values_normalize_to_current_goal():
    headers = [
        SessionResult(
            schema_version=3,
            session_id="s1",
            started_at=1.0,
            duration_ns=60_000_000_000,
            layout="qwerty",
            mode=Mode.ADAPTIVE,
            lesson_alphabet=(),
            focus_key=ord("e"),
            total_keystrokes=50,
            correct_keystrokes=50,
            key_confidence={ord("e"): 1.0},
            target_speed_cpm=300,
        ),
    ]
    values = key_confidence_values(headers, ord("e"), current_target_speed_cpm=600)
    assert values == [0.5]


def test_key_confidence_values_legacy_session_unnormalized():
    headers = [
        SessionResult(
            schema_version=3,
            session_id="s1",
            started_at=1.0,
            duration_ns=60_000_000_000,
            layout="qwerty",
            mode=Mode.ADAPTIVE,
            lesson_alphabet=(),
            focus_key=ord("e"),
            total_keystrokes=50,
            correct_keystrokes=50,
            key_confidence={ord("e"): 0.82},
            target_speed_cpm=0,
        ),
    ]
    values = key_confidence_values(headers, ord("e"), current_target_speed_cpm=600)
    assert values == [0.82]


def test_format_focus_confidence_trend_line_normalizes_to_current_goal():
    headers = [
        SessionResult(
            schema_version=3,
            session_id="s1",
            started_at=1.0,
            duration_ns=60_000_000_000,
            layout="qwerty",
            mode=Mode.ADAPTIVE,
            lesson_alphabet=(),
            focus_key=ord("e"),
            total_keystrokes=50,
            correct_keystrokes=50,
            key_confidence={ord("e"): 1.0},
            target_speed_cpm=300,
        ),
    ]
    line = format_focus_confidence_trend_line(headers, current_target_speed_cpm=600)
    assert "latest     0.50" in line
    assert "peak     0.50" in line


def test_format_key_confidence_trend_line_includes_cumulative():
    headers = [
        SessionResult(
            schema_version=3,
            session_id="s1",
            started_at=1.0,
            duration_ns=60_000_000_000,
            layout="qwerty",
            mode=Mode.ADAPTIVE,
            lesson_alphabet=(),
            focus_key=ord("e"),
            total_keystrokes=50,
            correct_keystrokes=50,
            key_confidence={ord("e"): 0.75},
        ),
    ]
    line = format_key_confidence_trend_line(headers, ord("e"), cumulative=1.1)
    assert "'e' confidence" in line
    assert "[cyan]" in line
    assert "latest 0.75" in line
    assert "cumulative 1.10" in line


def test_format_key_metric_trend_block_shows_key_once_with_colors():
    headers = [
        SessionResult(
            schema_version=3,
            session_id="s1",
            started_at=1.0,
            duration_ns=60_000_000_000,
            layout="qwerty",
            mode=Mode.ADAPTIVE,
            lesson_alphabet=(),
            focus_key=ord("e"),
            total_keystrokes=50,
            correct_keystrokes=50,
            key_confidence={ord("e"): 0.75},
        ),
    ]
    detail = format_key_metric_trend_block(
        title="'e'",
        headers=headers,
        codepoint=ord("e"),
        speed_values=[120.0],
        accuracy_values=[0.95],
    )
    assert detail.startswith("[bold]'e'[/] (1 sessions)")
    assert detail.count("sessions") == 1
    assert "'e' confidence" not in detail
    assert "[bold cyan]confidence[/]" in detail
    assert "[bold green]speed     [/]" in detail
    assert "[bold yellow]accuracy  [/]" in detail
    assert detail.count("'e'") == 1
    assert "latest   120.00" in detail
    assert "latest    95.0%" in detail


def test_format_aggregate_metric_trend_block_includes_title():
    detail = format_aggregate_metric_trend_block(
        title="Layout",
        confidence_values=[0.75],
        speed_values=[120.0],
        accuracy_values=[0.95],
    )
    assert detail.startswith("[bold]Layout[/] (1 sessions)")
    assert "[bold cyan]confidence[/]" in detail
    assert "[bold green]speed     [/]" in detail
    assert "[bold yellow]accuracy  [/]" in detail


def test_format_key_speed_trend_line_uses_green():
    line = format_key_speed_trend_line([100.0, 120.0])
    assert "[bold green]speed[/]" in line
    assert "[green]" in line


def test_wpm_sparkline_scales_oldest_to_newest():
    headers = [
        SessionResult(
            schema_version=2,
            session_id="s1",
            started_at=1.0,
            duration_ns=60_000_000_000,
            layout="qwerty",
            mode=Mode.ADAPTIVE,
            lesson_alphabet=(),
            focus_key=None,
            total_keystrokes=50,
            correct_keystrokes=50,
            words_completed=10,
        ),
        SessionResult(
            schema_version=2,
            session_id="s2",
            started_at=2.0,
            duration_ns=30_000_000_000,
            layout="qwerty",
            mode=Mode.ADAPTIVE,
            lesson_alphabet=(),
            focus_key=None,
            total_keystrokes=50,
            correct_keystrokes=50,
            words_completed=10,
        ),
    ]
    spark = wpm_sparkline(headers)
    assert len(spark) == 2
    assert spark[0] <= spark[1]  # 50 wpm then 100 wpm


def test_format_wpm_trend_line_includes_latest_and_peak():
    headers = [
        SessionResult(
            schema_version=2,
            session_id="s1",
            started_at=1.0,
            duration_ns=60_000_000_000,
            layout="qwerty",
            mode=Mode.ADAPTIVE,
            lesson_alphabet=(),
            focus_key=None,
            total_keystrokes=50,
            correct_keystrokes=50,
            words_completed=10,
        ),
    ]
    line = format_wpm_trend_line(headers)
    assert "WPM trend" in line
    assert "latest 10" in line
