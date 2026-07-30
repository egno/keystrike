from __future__ import annotations

from dataclasses import replace
from typing import TypedDict

from keystrike.application.session_use_cases import (
    AbortSession,
    FinishSession,
    RecordKeystroke,
    SessionStatsBaseline,
    StartSession,
    compute_accuracy,
    compute_wpm,
    confidence_window_session_baseline,
    count_words_completed,
    focus_confidence_sparkline,
    format_focus_confidence_trend_line,
    format_key_confidence_trend_line,
    format_key_speed_trend_line,
    format_metric_trend_block,
    format_session_stats_line,
    format_wpm_trend_line,
    key_confidence_sparkline,
    key_confidence_values,
    previous_session_header,
    wpm_sparkline,
)
from keystrike.domain.aggregate import combine_sessions
from keystrike.domain.confidence import (
    CONFIDENCE_SESSION_WINDOW,
    compute_unlocked,
    confidence_of,
    target_ms_per_char,
)
from keystrike.domain.enums import Mode, SessionState
from keystrike.domain.learn_order import keyboard_order
from keystrike.domain.models import SessionResult, Settings
from keystrike.infrastructure.layout_repo import BUNDLED_LAYOUTS
from tests.fakes import (
    FakeAggregatesCache,
    FakeClock,
    FakeIdGenerator,
    FakeLayoutRepository,
    FakeSessionRepository,
    FakeSettingsRepository,
)


class _SessionStatsCommon(TypedDict):
    schema_version: int
    started_at: float
    duration_ns: int
    layout: str
    mode: Mode
    lesson_alphabet: tuple[()]
    focus_key: None
    words_completed: int


def _session_stats_common(*, duration_ns: int = 60_000_000_000) -> _SessionStatsCommon:
    return _SessionStatsCommon(
        schema_version=3,
        started_at=1.0,
        duration_ns=duration_ns,
        layout="qwerty",
        mode=Mode.ADAPTIVE,
        lesson_alphabet=(),
        focus_key=None,
        words_completed=1,
    )


def _drive(text: str, keys: str, clock: FakeClock, id_gen: FakeIdGenerator,
           repo: FakeSessionRepository | None = None):
    start = StartSession(clock=clock, id_gen=id_gen)
    repo = repo if repo is not None else FakeSessionRepository()
    record = RecordKeystroke(clock=clock)
    finish = FinishSession(clock=clock, repo=repo)
    session = start(text, layout="qwerty", mode=Mode.ADAPTIVE)
    for i, ch in enumerate(keys, start=1):
        clock.advance(100_000_000)  # 100 ms per keystroke → 120 wpm on all-correct
        record(session, ch)
        if session.finished:
            break
        _ = i
    return session, finish(session)


def test_perfect_run(clock, id_gen):
    session, result = _drive("abc", "abc", clock, id_gen)
    assert session.state is SessionState.COMPLETE
    assert result.total_keystrokes == 3
    assert result.correct_keystrokes == 3
    assert compute_accuracy(result) == 1.0


def test_abort_session_marks_cancelled(clock, id_gen):
    session = StartSession(clock=clock, id_gen=id_gen)("ab", layout="qwerty", mode=Mode.ADAPTIVE)
    AbortSession()(session)
    assert session.state is SessionState.CANCELLED


def test_wrong_then_correct(clock, id_gen):
    # Type 'x' (wrong), then 'a' (correct), then 'b', 'c'
    _, result = _drive("abc", "xabc", clock, id_gen)
    assert result.total_keystrokes == 4
    assert result.correct_keystrokes == 3
    assert compute_accuracy(result) == 0.75


def test_backspace_is_a_noop(clock, id_gen):
    start = StartSession(clock=clock, id_gen=id_gen)
    record = RecordKeystroke(clock=clock)
    session = start("ab", layout="qwerty", mode=Mode.ADAPTIVE)

    record(session, "a")
    assert session.position == 1
    record.backspace(session)
    assert session.position == 1


def test_record_keystroke_backspace_convenience_method(clock, id_gen):
    start = StartSession(clock=clock, id_gen=id_gen)
    record = RecordKeystroke(clock=clock)
    session = start("ab", layout="qwerty", mode=Mode.ADAPTIVE)
    record(session, "a")
    assert session.position == 1
    record.backspace(session)
    assert session.position == 1


def test_repo_receives_keystrokes(clock, id_gen, session_repo):
    session, _ = _drive("hi", "hi", clock, id_gen, repo=session_repo)
    assert len(session_repo.keystrokes[session.id]) == 2
    assert len(session_repo.headers) == 1


def test_in_progress_keystrokes_not_persisted(clock, id_gen, session_repo):
    start = StartSession(clock=clock, id_gen=id_gen)
    record = RecordKeystroke(clock=clock)
    session = start("ab", layout="qwerty", mode=Mode.ADAPTIVE)
    clock.advance(100_000_000)
    record(session, "a")
    assert session_repo.keystrokes == {}
    assert session_repo.headers == []


def test_aborted_session_not_persisted(clock, id_gen, session_repo):
    start = StartSession(clock=clock, id_gen=id_gen)
    record = RecordKeystroke(clock=clock)
    session = start("ab", layout="qwerty", mode=Mode.ADAPTIVE)
    clock.advance(100_000_000)
    record(session, "a")
    AbortSession()(session)
    assert session_repo.keystrokes == {}
    assert session_repo.headers == []


def test_wpm_math(clock, id_gen):
    # Timer starts at the first keystroke, not session creation: "hello" is 1 word,
    # 5 keystrokes span 4 intervals of 100ms = 0.4s → 150 wpm.
    _, result = _drive("hello", "hello", clock, id_gen)
    assert result.words_completed == 1
    assert 149.0 < compute_wpm(result) < 151.0


def test_count_words_completed():
    assert count_words_completed("hello world", 0) == 0
    assert count_words_completed("hello world", 5) == 1
    assert count_words_completed("hello world", 6) == 1
    assert count_words_completed("hello world", 7) == 1
    assert count_words_completed("hello world", 11) == 2
    assert count_words_completed("hello", 3) == 0
    assert count_words_completed("hello", 5) == 1


def test_timer_does_not_start_until_first_keystroke(clock, id_gen):
    start = StartSession(clock=clock, id_gen=id_gen)
    record = RecordKeystroke(clock=clock)
    finish = FinishSession(clock=clock)
    session = start("ab", layout="qwerty", mode=Mode.ADAPTIVE)

    clock.advance(10_000_000_000)  # 10s of "thinking time" before typing anything
    assert session.typing_started_at_ns is None

    clock.advance(100_000_000)
    record(session, "a")
    assert session.typing_started_at_ns is not None

    clock.advance(100_000_000)
    record(session, "b")

    result = finish(session)
    # Duration only spans the two keystrokes (100ms), not the 10s thinking time.
    assert result.duration_ns == 100_000_000


def test_leading_space_enter_tab_ignored_before_first_keystroke(clock, id_gen):
    start = StartSession(clock=clock, id_gen=id_gen)
    record = RecordKeystroke(clock=clock)
    session = start("abc", layout="qwerty", mode=Mode.ADAPTIVE)

    for ch in (" ", "\t", "\n", "\r"):
        record(session, ch)

    assert session.typing_started_at_ns is None
    assert session.keystrokes == []
    assert session.position == 0

    record(session, "a")
    assert session.typing_started_at_ns is not None
    assert session.position == 1


def test_leading_space_honored_when_target_starts_with_space(clock, id_gen):
    start = StartSession(clock=clock, id_gen=id_gen)
    record = RecordKeystroke(clock=clock)
    session = start(" ab", layout="qwerty", mode=Mode.ADAPTIVE)

    record(session, " ")
    assert session.position == 1
    assert len(session.keystrokes) == 1
    assert session.keystrokes[0].correct


def test_leading_enter_honored_when_target_starts_with_newline(clock, id_gen):
    start = StartSession(clock=clock, id_gen=id_gen)
    record = RecordKeystroke(clock=clock)
    session = start("\nabc", layout="qwerty", mode=Mode.ADAPTIVE)

    record(session, "\r")
    assert session.position == 1
    assert len(session.keystrokes) == 1
    assert session.keystrokes[0].correct


def test_learn_timer_pauses_after_idle(clock, id_gen):
    start = StartSession(clock=clock, id_gen=id_gen)
    record = RecordKeystroke(clock=clock)
    finish = FinishSession(clock=clock)
    session = start("ab", layout="qwerty", mode=Mode.ADAPTIVE)

    record(session, "a")
    clock.advance(2_000_000_000)
    record(session, "b")
    clock.advance(10_000_000_000)  # 10s idle — only 5s grace counts after last key

    result = finish(session)
    assert result.duration_ns == 7_000_000_000


def test_learn_timer_resumes_after_idle(clock, id_gen):
    start = StartSession(clock=clock, id_gen=id_gen)
    record = RecordKeystroke(clock=clock)
    finish = FinishSession(clock=clock)
    session = start("abc", layout="qwerty", mode=Mode.ADAPTIVE)

    record(session, "a")
    clock.advance(2_000_000_000)
    record(session, "b")
    clock.advance(10_000_000_000)  # idle: active frozen at 2s + 5s grace = 7s
    clock.advance(1_000_000_000)
    record(session, "c")

    result = finish(session)
    assert result.duration_ns == 7_000_000_000


def test_format_session_stats_line(clock, id_gen):
    _, result = _drive("hello", "hello", clock, id_gen)
    line = format_session_stats_line(result)
    assert line.startswith("Last: WPM")
    assert "Acc" in line
    assert "Time" in line
    assert "Keys" not in line
    assert "↑" not in line
    assert "↓" not in line


def test_format_session_stats_line_shows_deltas_vs_confidence_baseline(clock, id_gen):
    repo = FakeSessionRepository()
    start = StartSession(clock=clock, id_gen=id_gen)
    record = RecordKeystroke(clock=clock)
    finish = FinishSession(clock=clock, repo=repo)

    slow = start("ab", layout="qwerty", mode=Mode.ADAPTIVE)
    clock.advance(200_000_000)
    record(slow, "a")
    clock.advance(200_000_000)
    record(slow, "b")
    first = finish(slow)

    fast = start("ab", layout="qwerty", mode=Mode.ADAPTIVE)
    clock.advance(100_000_000)
    record(fast, "a")
    clock.advance(100_000_000)
    record(fast, "b")
    second = finish(fast)

    baseline = confidence_window_session_baseline(repo, second, window=10)
    assert baseline is not None
    assert baseline.wpm == compute_wpm(first)
    line = format_session_stats_line(second, baseline=baseline)
    assert "[green]↑" in line


def test_format_session_stats_line_uses_window_not_previous_only():
    slow = SessionResult(
        session_id="s1",
        total_keystrokes=10,
        correct_keystrokes=10,
        **_session_stats_common(),
    )
    fast = SessionResult(
        session_id="s2",
        total_keystrokes=10,
        correct_keystrokes=10,
        **_session_stats_common(duration_ns=30_000_000_000),
    )
    medium = SessionResult(
        session_id="s3",
        total_keystrokes=10,
        correct_keystrokes=10,
        **_session_stats_common(duration_ns=33_333_333_333),
    )
    repo = FakeSessionRepository(headers=[slow, fast, medium])

    baseline = confidence_window_session_baseline(repo, medium, window=10)
    assert baseline is not None
    assert baseline.wpm < compute_wpm(fast)
    assert baseline.wpm > compute_wpm(slow)

    vs_previous = format_session_stats_line(
        medium, baseline=SessionStatsBaseline(
            wpm=compute_wpm(fast),
            accuracy_pct=compute_accuracy(fast) * 100,
        ),
    )
    vs_window = format_session_stats_line(medium, baseline=baseline)
    assert "[red]↓" in vs_previous
    assert "[green]↑" in vs_window


def test_format_session_stats_line_shows_accuracy_regression():
    previous = SessionResult(
        session_id="s1",
        total_keystrokes=10,
        correct_keystrokes=10,
        **_session_stats_common(),
    )
    current = SessionResult(
        session_id="s2",
        total_keystrokes=10,
        correct_keystrokes=8,
        **_session_stats_common(),
    )
    line = format_session_stats_line(
        current,
        baseline=SessionStatsBaseline(
            wpm=compute_wpm(previous),
            accuracy_pct=compute_accuracy(previous) * 100,
        ),
    )
    assert "[red]↓" in line


def test_confidence_window_session_baseline_none_for_first_session(clock, id_gen):
    repo = FakeSessionRepository()
    _, result = _drive("ab", "ab", clock, id_gen, repo=repo)
    assert confidence_window_session_baseline(repo, result, window=10) is None


def test_previous_session_header_skips_current(clock, id_gen):
    repo = FakeSessionRepository()
    _, first = _drive("ab", "ab", clock, id_gen, repo=repo)
    clock.advance(1_000_000_000)
    _, second = _drive("ab", "ab", clock, id_gen, repo=repo)
    assert previous_session_header(repo, second) == first
    assert previous_session_header(repo, first) is None


def test_finish_session_persists_unlocked_keys(clock, id_gen):
    settings_repo = FakeSettingsRepository()
    layout_repo = FakeLayoutRepository(dict(BUNDLED_LAYOUTS))
    repo = FakeSessionRepository()
    finish = FinishSession(
        clock=clock,
        repo=repo,
        aggregates_cache=FakeAggregatesCache(),
        settings_repo=settings_repo,
        layout_repo=layout_repo,
    )
    start = StartSession(clock=clock, id_gen=id_gen)
    record = RecordKeystroke(clock=clock)
    session = start("ab", layout="qwerty", mode=Mode.ADAPTIVE)
    clock.advance(100_000_000)
    record(session, "a")
    clock.advance(100_000_000)
    record(session, "b")
    result = finish(session)

    settings = settings_repo.load()
    layout = layout_repo.get("qwerty")
    expected = compute_unlocked(
        keyboard_order(layout),
        settings.alphabet_size,
        {},
        target_ms_per_char(settings.target_speed_cpm),
    )
    assert result.unlocked_keys == expected
    assert len(repo.headers) == 1
    assert repo.headers[0].unlocked_keys == expected


def test_finish_session_bumps_alphabet_size_when_unlocked_set_grows(clock, id_gen):
    layout = BUNDLED_LAYOUTS["qwerty"]
    order = keyboard_order(layout)
    settings_repo = FakeSettingsRepository(Settings(alphabet_size=5))
    layout_repo = FakeLayoutRepository(dict(BUNDLED_LAYOUTS))
    repo = FakeSessionRepository()
    finish = FinishSession(
        clock=clock,
        repo=repo,
        settings_repo=settings_repo,
        layout_repo=layout_repo,
    )
    start = StartSession(clock=clock, id_gen=id_gen)
    record = RecordKeystroke(clock=clock)

    warmup = "".join(chr(cp) for cp in order[:5] for _ in range(10))
    warmup_session = start(
        warmup, layout="qwerty", mode=Mode.ADAPTIVE, focus_key=order[0],
    )
    for ch in warmup:
        clock.advance(50_000_000)
        record(warmup_session, ch)
    finish(warmup_session)

    session = start("as", layout="qwerty", mode=Mode.ADAPTIVE, focus_key=order[0])
    for ch in "as":
        clock.advance(100_000_000)
        record(session, ch)
    result = finish(session)

    assert len(result.unlocked_keys) > 5
    assert settings_repo.settings.alphabet_size == len(result.unlocked_keys)


def test_finish_session_persists_key_confidence(clock, id_gen):
    settings_repo = FakeSettingsRepository()
    layout_repo = FakeLayoutRepository(dict(BUNDLED_LAYOUTS))
    repo = FakeSessionRepository()
    finish = FinishSession(
        clock=clock,
        repo=repo,
        aggregates_cache=FakeAggregatesCache(),
        settings_repo=settings_repo,
        layout_repo=layout_repo,
    )
    start = StartSession(clock=clock, id_gen=id_gen)
    record = RecordKeystroke(clock=clock)
    session = start("ab", layout="qwerty", mode=Mode.ADAPTIVE, focus_key=ord("a"))
    clock.advance(100_000_000)
    record(session, "a")
    clock.advance(100_000_000)
    record(session, "b")
    result = finish(session)

    settings = settings_repo.load()
    layout = layout_repo.get("qwerty")
    target = target_ms_per_char(settings.target_speed_cpm)
    expected_unlocked = compute_unlocked(
        keyboard_order(layout),
        settings.alphabet_size,
        {},
        target,
    )
    assert result.schema_version == 3
    assert set(result.key_confidence.keys()) == set(expected_unlocked)
    stats = combine_sessions([(result, session.keystrokes)]).keys
    for cp in expected_unlocked:
        assert result.key_confidence[cp] == confidence_of(cp, stats, target)
    assert repo.headers[0].key_confidence == result.key_confidence


def test_finish_session_key_confidence_uses_confidence_session_window(clock, id_gen):
    settings_repo = FakeSettingsRepository()
    layout_repo = FakeLayoutRepository(dict(BUNDLED_LAYOUTS))
    repo = FakeSessionRepository()
    finish = FinishSession(
        clock=clock,
        repo=repo,
        settings_repo=settings_repo,
        layout_repo=layout_repo,
    )
    start = StartSession(clock=clock, id_gen=id_gen)
    record = RecordKeystroke(clock=clock)

    for _ in range(CONFIDENCE_SESSION_WINDOW - 1):
        session = start("a", layout="qwerty", mode=Mode.ADAPTIVE, focus_key=ord("a"))
        clock.advance(400_000_000)
        record(session, "a")
        finish(session)

    session = start("a", layout="qwerty", mode=Mode.ADAPTIVE, focus_key=ord("a"))
    clock.advance(100_000_000)
    record(session, "a")
    result = finish(session)

    settings = settings_repo.load()
    target = target_ms_per_char(settings.target_speed_cpm)
    prior = sorted(repo.headers, key=lambda h: h.started_at)[-(CONFIDENCE_SESSION_WINDOW - 1):]
    stats = combine_sessions(
        [(header, repo.keystrokes[header.session_id]) for header in prior]
        + [(result, session.keystrokes)],
    ).keys
    assert result.key_confidence[ord("a")] == confidence_of(ord("a"), stats, target)


def test_finish_session_persists_target_speed_cpm(clock, id_gen):
    settings_repo = FakeSettingsRepository()
    settings_repo.settings = replace(settings_repo.settings, target_speed_cpm=400)
    layout_repo = FakeLayoutRepository(dict(BUNDLED_LAYOUTS))
    repo = FakeSessionRepository()
    finish = FinishSession(
        clock=clock,
        repo=repo,
        aggregates_cache=FakeAggregatesCache(),
        settings_repo=settings_repo,
        layout_repo=layout_repo,
    )
    start = StartSession(clock=clock, id_gen=id_gen)
    record = RecordKeystroke(clock=clock)
    session = start("a", layout="qwerty", mode=Mode.ADAPTIVE, focus_key=ord("a"))
    clock.advance(100_000_000)
    record(session, "a")
    result = finish(session)

    assert result.target_speed_cpm == 400
    assert repo.headers[0].target_speed_cpm == 400


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
    key_line = format_metric_trend_block(
        title="'b'",
        headers=headers,
        codepoint=ord("b"),
        confidence_values=key_confidence_values(headers, ord("b")),
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


def test_format_metric_trend_block_key_detail_shows_key_once_with_colors():
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
    detail = format_metric_trend_block(
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


def test_format_metric_trend_block_aggregate_includes_title():
    detail = format_metric_trend_block(
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
    assert "peak 10" in line
