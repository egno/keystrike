from __future__ import annotations

from keystrike.application.session_use_cases import (
    AbortSession,
    FinishSession,
    RecordKeystroke,
    StartSession,
    compute_accuracy,
    compute_wpm,
    count_words_completed,
    focus_confidence_sparkline,
    format_focus_confidence_trend_line,
    format_key_confidence_trend_line,
    format_session_stats_line,
    format_wpm_trend_line,
    key_confidence_sparkline,
    key_confidence_values,
    wpm_sparkline,
)
from keystrike.domain.aggregate import aggregate_session, combine
from keystrike.domain.confidence import compute_unlocked, confidence_of, target_ms_per_char
from keystrike.domain.enums import Mode, SessionState
from keystrike.domain.learn_order import keyboard_order
from keystrike.domain.models import SessionResult
from keystrike.infrastructure.layout_repo import BUNDLED_LAYOUTS
from tests.fakes import (
    FakeAggregatesCache,
    FakeClock,
    FakeIdGenerator,
    FakeLayoutRepository,
    FakeSessionRepository,
    FakeSettingsRepository,
)


def _drive(text: str, keys: str, clock: FakeClock, id_gen: FakeIdGenerator,
           repo: FakeSessionRepository | None = None):
    start = StartSession(clock=clock, id_gen=id_gen)
    repo = repo if repo is not None else FakeSessionRepository()
    record = RecordKeystroke(clock=clock, repo=repo)
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


def test_format_session_stats_line(clock, id_gen):
    _, result = _drive("hello", "hello", clock, id_gen)
    line = format_session_stats_line(result)
    assert line.startswith("Last: WPM")
    assert "Acc" in line
    assert "Keys" in line


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
    record = RecordKeystroke(clock=clock, repo=repo)
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
    record = RecordKeystroke(clock=clock, repo=repo)
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
    stats = combine({}, aggregate_session(result, session.keystrokes))
    for cp in expected_unlocked:
        assert result.key_confidence[cp] == confidence_of(cp, stats, target)
    assert repo.headers[0].key_confidence == result.key_confidence


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
    assert "Focus 'e' confidence" in line
    assert "latest 0.75" in line
    assert "peak 0.75" in line


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
    assert "latest 0.75" in line
    assert "cumulative 1.10" in line


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
