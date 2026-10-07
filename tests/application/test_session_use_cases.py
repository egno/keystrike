from __future__ import annotations

from dataclasses import replace
from random import Random
from typing import TypedDict

from keystrike.application.build_lesson import BuildLesson
from keystrike.application.session_queries import (
    compute_accuracy,
    compute_wpm,
    latest_session_header,
    previous_session_header,
    session_wpm_below_target,
)
from keystrike.application.session_use_cases import (
    AbortSession,
    FinishSession,
    RecordKeystroke,
    SessionStatsBaseline,
    StartSession,
    confidence_window_session_baseline,
    count_words_completed,
)
from keystrike.application.stats_use_cases import RebuildAggregates
from keystrike.domain.aggregate import combine_sessions
from keystrike.domain.confidence import confidence_of, target_ms_per_char
from keystrike.domain.enums import Mode, SessionState
from keystrike.domain.generator import wpm_from_cpm
from keystrike.domain.learn_order import keyboard_order
from keystrike.domain.models import (
    CONFIDENCE_SESSION_WINDOW,
    SessionResult,
    Settings,
    UnlockTuning,
    WordGenBounds,
)
from keystrike.domain.unlock import compute_unlocked
from keystrike.infrastructure.layout_repo import BUNDLED_LAYOUTS
from keystrike.presentation.formatting.trends import format_session_stats_line
from tests.fakes import (
    FakeAggregatesCache,
    FakeClock,
    FakeIdGenerator,
    FakeLanguageProvider,
    FakeLayoutRepository,
    FakeSessionRepository,
    FakeSettingsRepository,
    FakeWordListStore,
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
        schema_version=4,
        started_at=1.0,
        duration_ns=duration_ns,
        layout="qwerty",
        mode=Mode.ADAPTIVE,
        lesson_alphabet=(),
        focus_key=None,
        words_completed=1,
    )


def _drive(
    text: str,
    keys: str,
    clock: FakeClock,
    id_gen: FakeIdGenerator,
    repo: FakeSessionRepository | None = None,
):
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
    assert len(session_repo.headers) == 1
    saved = session_repo.headers[0]
    assert saved.session_id == session.id
    assert saved.stats.keys[ord("h")].attempts == 1
    assert saved.stats.keys[ord("i")].attempts == 1


def test_in_progress_keystrokes_not_persisted(clock, id_gen, session_repo):
    start = StartSession(clock=clock, id_gen=id_gen)
    record = RecordKeystroke(clock=clock)
    session = start("ab", layout="qwerty", mode=Mode.ADAPTIVE)
    clock.advance(100_000_000)
    record(session, "a")
    assert session_repo.headers == []


def test_aborted_session_not_persisted(clock, id_gen, session_repo):
    start = StartSession(clock=clock, id_gen=id_gen)
    record = RecordKeystroke(clock=clock)
    session = start("ab", layout="qwerty", mode=Mode.ADAPTIVE)
    clock.advance(100_000_000)
    record(session, "a")
    AbortSession()(session)
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


def test_repeated_leading_skip_keys_ignored_after_required_char(clock, id_gen):
    start = StartSession(clock=clock, id_gen=id_gen)
    record = RecordKeystroke(clock=clock)

    session = start(" ab", layout="qwerty", mode=Mode.ADAPTIVE)
    record(session, " ")
    record(session, " ")
    record(session, " ")
    assert session.position == 1
    assert session.total_count == 1

    session = start("\nabc", layout="qwerty", mode=Mode.ADAPTIVE)
    record(session, "\n")
    record(session, "\n")
    assert session.position == 1
    assert session.total_count == 1


def test_repeated_leading_skip_keys_ignored_at_word_start(clock, id_gen):
    start = StartSession(clock=clock, id_gen=id_gen)
    record = RecordKeystroke(clock=clock)
    session = start("hi there", layout="qwerty", mode=Mode.ADAPTIVE)

    for ch in "hi ":
        record(session, ch)
    record(session, " ")
    record(session, "\t")

    assert session.position == 3
    assert session.total_count == 3
    assert session.error_positions == set()

    record(session, "t")
    assert session.position == 4


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
        medium,
        baseline=SessionStatsBaseline(
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


def test_latest_session_header_picks_most_recent_by_started_at():
    older = SessionResult(
        session_id="s1", total_keystrokes=1, correct_keystrokes=1, **_session_stats_common()
    )
    newer = replace(older, session_id="s2", started_at=2.0)
    repo = FakeSessionRepository(headers=[older, newer])
    assert latest_session_header(repo, "qwerty") == newer


def test_latest_session_header_none_when_no_sessions():
    assert latest_session_header(FakeSessionRepository(), "qwerty") is None


def test_session_wpm_below_target_true_when_slower_than_target(clock, id_gen):
    _, result = _drive("hello world", "hello ", clock, id_gen)
    result = replace(result, words_completed=1, duration_ns=60_000_000_000, target_speed_cpm=300)
    assert session_wpm_below_target(result) is True


def test_session_wpm_below_target_false_when_faster_than_target(clock, id_gen):
    _, result = _drive("hello world", "hello ", clock, id_gen)
    result = replace(result, words_completed=20, duration_ns=1_000_000_000, target_speed_cpm=300)
    assert session_wpm_below_target(result) is False


def test_session_wpm_below_target_false_for_legacy_session_without_target():
    result = SessionResult(
        session_id="s1",
        total_keystrokes=1,
        correct_keystrokes=1,
        **_session_stats_common(),
    )
    assert result.target_speed_cpm == 0
    assert session_wpm_below_target(result) is False


def _drive_at_pace(text: str, ms_per_keystroke: int, target_speed_cpm: int) -> SessionResult:
    clock = FakeClock()
    settings_repo = FakeSettingsRepository(Settings(target_speed_cpm=target_speed_cpm))
    session = StartSession(clock=clock, id_gen=FakeIdGenerator())(
        text, layout="qwerty", mode=Mode.ADAPTIVE
    )
    record = RecordKeystroke(clock=clock)
    for ch in text:
        clock.advance(ms_per_keystroke * 1_000_000)
        record(session, ch)
    return FinishSession(clock=clock, settings_repo=settings_repo)(session)


# 12 words x 3 letters + 11 spaces = 47 keystrokes (default lesson, 2-4 bounds).
_TWELVE_WORD_LESSON = " ".join(["abc"] * 12)


def test_session_wpm_below_target_false_when_every_key_is_at_target_speed():
    """40 WPM in Settings is 120 CPM (500 ms per key). Typing every keystroke,
    spaces included, at exactly 500 ms meets the target: the gate counts the
    spaces, so it must not fire. WPM against cpm / mean word length (40) would."""
    result = _drive_at_pace(_TWELVE_WORD_LESSON, 500, target_speed_cpm=120)
    assert result.correct_keystrokes == 47
    assert result.words_completed == 12
    a = result.stats.keys[ord("a")]
    assert a.time_ns / a.samples == 500_000_000  # key speed exactly 1.0
    assert compute_wpm(result) < wpm_from_cpm(120)  # the old comparison fired here
    assert session_wpm_below_target(result) is False


def test_session_wpm_below_target_true_when_keys_slower_than_target():
    result = _drive_at_pace(_TWELVE_WORD_LESSON, 550, target_speed_cpm=120)
    assert session_wpm_below_target(result) is True


def test_session_wpm_below_target_ignores_word_length_bounds():
    """Keystrokes per minute need no word-length guess, so word-list lessons
    (3-10 letters) are judged the same way as generated ones."""
    result = _drive_at_pace(_TWELVE_WORD_LESSON, 500, target_speed_cpm=120)
    wide = replace(result, generated_min_len=3, generated_max_len=10)
    assert session_wpm_below_target(wide) is False


def test_finish_session_persists_generated_word_bounds(clock, id_gen):
    settings_repo = FakeSettingsRepository(Settings(word_gen=WordGenBounds(min_len=3, max_len=8)))
    finish = FinishSession(clock=clock, settings_repo=settings_repo)
    start = StartSession(clock=clock, id_gen=id_gen)
    record = RecordKeystroke(clock=clock)
    session = start("ab", layout="qwerty", mode=Mode.ADAPTIVE)
    clock.advance(100_000_000)
    record(session, "a")
    result = finish(session)
    assert result.generated_min_len == 3
    assert result.generated_max_len == 8


def test_finish_session_persists_unlocked_keys(clock, id_gen):
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


def test_finish_session_does_not_bump_alphabet_size_immediately(clock, id_gen):
    """FinishSession reports the grown unlocked set on the result, but must
    not persist it back to Settings.alphabet_size right away -- that eager
    write caused a distracting mid-session status jump. Persisting the
    growth is BuildLesson's job, done once, right before the next lesson is
    generated (see alphabet_sync.sync_alphabet_size)."""
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

    newest = chr(order[4])
    cohort_drill = "".join(
        (chr(peer) + newest) * 8 + (newest + chr(peer)) * 8 for peer in order[2:4]
    )
    warmup = "".join(chr(cp) for _ in range(15) for cp in order[:5]) + cohort_drill
    warmup_session = start(
        warmup,
        layout="qwerty",
        mode=Mode.ADAPTIVE,
        focus_key=order[0],
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
    assert settings_repo.settings.alphabet_size == 5


def test_finish_session_respects_next_letter_unlock_threshold_setting(clock, id_gen):
    """Same warmup drill as test_finish_session_bumps_alphabet_size_when_unlocked_set_grows,
    but with the threshold raised out of reach -- alphabet_size must not
    grow, proving Settings.next_letter_unlock_threshold is actually wired
    into FinishSession's compute_unlocked call."""
    layout = BUNDLED_LAYOUTS["qwerty"]
    order = keyboard_order(layout)
    settings_repo = FakeSettingsRepository(
        Settings(alphabet_size=5, unlock=UnlockTuning(next_letter_unlock_threshold=10.0))
    )
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

    newest = chr(order[4])
    cohort_drill = "".join(
        (chr(peer) + newest) * 8 + (newest + chr(peer)) * 8 for peer in order[2:4]
    )
    warmup = "".join(chr(cp) for _ in range(15) for cp in order[:5]) + cohort_drill
    warmup_session = start(
        warmup,
        layout="qwerty",
        mode=Mode.ADAPTIVE,
        focus_key=order[0],
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

    assert len(result.unlocked_keys) == 5
    assert settings_repo.settings.alphabet_size == 5


def test_finish_session_persists_key_confidence(clock, id_gen):
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
    assert result.schema_version == 5
    assert set(result.key_confidence.keys()) == set(expected_unlocked)
    stats = combine_sessions([(result, result.stats)]).keys
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
    prior = sorted(repo.headers, key=lambda h: h.started_at)[-(CONFIDENCE_SESSION_WINDOW - 1) :]
    stats = combine_sessions(
        [(header, header.stats) for header in prior] + [(result, result.stats)],
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


def test_finish_session_alphabet_bump_respects_transition_gate(clock, id_gen):
    """Regression: solo-mastering four keys without ever typing a bigram
    between them must not bump alphabet_size -- the old `_snapshot_unlock_state`
    computed `unlocked_keys` without passing `transitions` at all, so it
    silently persisted an ungated count. The next `BuildLesson` call then
    force-unlocked that many keys via `forced_count`, bypassing the
    transition gate entirely regardless of what `compute_unlocked` would
    otherwise require."""
    layout_name = "qwerty"
    layout = BUNDLED_LAYOUTS[layout_name]
    order = keyboard_order(layout)
    settings_repo = FakeSettingsRepository(Settings(alphabet_size=4))
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

    # Master a, s, h, d solo -- each in its OWN session, repeating a single
    # character, so no cross-key bigram is ever produced (same-key deltas
    # are dropped, see `without_same_key_transitions`).
    for cp in order[:4]:
        text = chr(cp) * 10
        session = start(text, layout=layout_name, mode=Mode.ADAPTIVE, focus_key=cp)
        for c in text:
            clock.advance(50_000_000)
            record(session, c)
        finish(session)

    assert settings_repo.settings.alphabet_size == 4

    aggregates_cache = FakeAggregatesCache()
    RebuildAggregates(repo=repo, cache=aggregates_cache, settings_repo=settings_repo)(layout_name)

    builder = BuildLesson(
        layout_repo=layout_repo,
        aggregates_cache=aggregates_cache,
        settings_repo=settings_repo,
        language_provider=FakeLanguageProvider(),
        wordlist_store=FakeWordListStore(),
        rng=Random(0),
        clock=clock,
    )
    lesson = builder(layout_name)
    unlocked_cps = {k.codepoint for k in lesson.state.keys}
    assert unlocked_cps == set(order[:4])
    assert order[4] not in unlocked_cps


def test_finish_session_saves_weakest_pair_typed_in_session(clock, id_gen):
    settings_repo = FakeSettingsRepository(
        Settings(
            target_speed_cpm=300,
            unlock=UnlockTuning(min_transition_confidence_attempts=2),
        )
    )
    repo = FakeSessionRepository()
    finish = FinishSession(
        clock=clock,
        repo=repo,
        settings_repo=settings_repo,
        layout_repo=FakeLayoutRepository(dict(BUNDLED_LAYOUTS)),
    )
    start = StartSession(clock=clock, id_gen=id_gen)
    record = RecordKeystroke(clock=clock)
    order = keyboard_order(BUNDLED_LAYOUTS["qwerty"])
    a, b = chr(order[0]), chr(order[1])
    session = start(f"{a}{b}{a}{b}", layout="qwerty", mode=Mode.ADAPTIVE, focus_key=order[0])
    for ch in f"{a}{b}{a}{b}":
        clock.advance(2_000_000_000)  # far slower than 300 cpm
        record(session, ch)
    result = finish(session)
    assert result.weakest_pair is not None
    assert {result.weakest_pair.prev_cp, result.weakest_pair.next_cp} == {order[0], order[1]}
    assert repo.headers[0].weakest_pair == result.weakest_pair


def _finish_typed(clock, id_gen, repo, text: str, step_ns: int, *, min_pair_attempts: int):
    """Type `text` at a fixed pace through Start/Record/FinishSession."""
    finish = FinishSession(
        clock=clock,
        repo=repo,
        settings_repo=FakeSettingsRepository(
            Settings(
                target_speed_cpm=300,
                unlock=UnlockTuning(min_transition_confidence_attempts=min_pair_attempts),
            )
        ),
        layout_repo=FakeLayoutRepository(dict(BUNDLED_LAYOUTS)),
    )
    session = StartSession(clock=clock, id_gen=id_gen)(
        text, layout="qwerty", mode=Mode.ADAPTIVE, focus_key=ord(text[0])
    )
    record = RecordKeystroke(clock=clock)
    for ch in text:
        clock.advance(step_ns)
        record(session, ch)
    return finish(session)


def test_finish_session_without_slow_pair_saves_none(clock, id_gen):
    order = keyboard_order(BUNDLED_LAYOUTS["qwerty"])
    a, b = chr(order[0]), chr(order[1])
    fast = 50_000_000  # well over 300 cpm
    result = _finish_typed(
        clock, id_gen, FakeSessionRepository(), f"{a}{b}{a}{b}", fast, min_pair_attempts=2
    )
    assert result.weakest_pair is None


def test_finish_session_skips_slow_pair_below_attempt_floor(clock, id_gen):
    order = keyboard_order(BUNDLED_LAYOUTS["qwerty"])
    a, b = chr(order[0]), chr(order[1])
    slow = 2_000_000_000
    result = _finish_typed(
        clock, id_gen, FakeSessionRepository(), f"{a}{b}", slow, min_pair_attempts=4
    )
    assert result.weakest_pair is None


def test_finish_session_skips_slow_pair_only_in_history(clock, id_gen):
    order = keyboard_order(BUNDLED_LAYOUTS["qwerty"])
    a, b = chr(order[0]), chr(order[1])
    slow = 2_000_000_000
    repo = FakeSessionRepository()
    first = _finish_typed(clock, id_gen, repo, f"{a}{b}{a}{b}", slow, min_pair_attempts=2)
    assert first.weakest_pair is not None
    # Same-key presses only: the slow pair stays in the window but is not typed.
    second = _finish_typed(clock, id_gen, repo, f"{a}{a}{a}", slow, min_pair_attempts=2)
    assert second.weakest_pair is None
