from __future__ import annotations

from keystrike.application.session_use_cases import (
    FinishSession,
    RecordKeystroke,
    StartSession,
    compute_accuracy,
    compute_wpm,
)
from keystrike.domain.enums import Mode, SessionState
from keystrike.domain.session import BACKSPACE
from tests.fakes import FakeClock, FakeIdGenerator, FakeSessionRepository


def _drive(text: str, keys: str, clock: FakeClock, id_gen: FakeIdGenerator,
           repo: FakeSessionRepository | None = None):
    start = StartSession(clock=clock, id_gen=id_gen)
    repo = repo if repo is not None else FakeSessionRepository()
    record = RecordKeystroke(clock=clock, repo=repo)
    finish = FinishSession(clock=clock, repo=repo)
    session = start(text, layout="qwerty", mode=Mode.FREE)
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


def test_wrong_then_correct(clock, id_gen):
    # Type 'x' (wrong), then 'a' (correct), then 'b', 'c'
    _, result = _drive("abc", "xabc", clock, id_gen)
    assert result.total_keystrokes == 4
    assert result.correct_keystrokes == 3
    assert compute_accuracy(result) == 0.75


def test_backspace_rewinds_cursor_without_double_count(clock, id_gen):
    start = StartSession(clock=clock, id_gen=id_gen)
    record = RecordKeystroke(clock=clock)
    finish = FinishSession(clock=clock)
    session = start("ab", layout="qwerty", mode=Mode.FREE)

    def step(char):
        clock.advance(50_000_000)
        record(session, char)

    step("a")               # correct → pos=1
    step("z")               # wrong   → pos still 1
    assert session.position == 1
    step(BACKSPACE)         # rewind  → pos=0
    assert session.position == 0
    step("a")               # correct → pos=1
    step("b")               # correct → pos=2

    result = finish(session)
    assert result.total_keystrokes == 4        # backspace not recorded
    assert result.correct_keystrokes == 3
    assert session.finished
    assert session.error_positions == {1}


def test_record_keystroke_backspace_convenience_method(clock, id_gen):
    start = StartSession(clock=clock, id_gen=id_gen)
    record = RecordKeystroke(clock=clock)
    session = start("ab", layout="qwerty", mode=Mode.FREE)
    record(session, "a")
    assert session.position == 1
    record.backspace(session)
    assert session.position == 0


def test_backspace_is_a_noop_in_adaptive_mode(clock, id_gen):
    start = StartSession(clock=clock, id_gen=id_gen)
    record = RecordKeystroke(clock=clock)
    session = start("ab", layout="qwerty", mode=Mode.ADAPTIVE)

    record(session, "a")
    assert session.position == 1
    record.backspace(session)
    assert session.position == 1  # unchanged — no correcting mistakes in adaptive mode


def test_backspace_still_works_in_code_mode(clock, id_gen):
    start = StartSession(clock=clock, id_gen=id_gen)
    record = RecordKeystroke(clock=clock)
    session = start("ab", layout="qwerty", mode=Mode.CODE)

    record(session, "a")
    assert session.position == 1
    record.backspace(session)
    assert session.position == 0


def test_repo_receives_keystrokes(clock, id_gen, session_repo):
    session, _ = _drive("hi", "hi", clock, id_gen, repo=session_repo)
    assert len(session_repo.keystrokes[session.id]) == 2
    assert len(session_repo.headers) == 1


def test_wpm_math(clock, id_gen):
    # Timer starts at the first keystroke, not session creation: 5 keystrokes
    # span 4 intervals of 100ms = 0.4s → 1 word / (0.4/60) min = 150 wpm.
    _, result = _drive("hello", "hello", clock, id_gen)
    assert 149.0 < compute_wpm(result) < 151.0


def test_timer_does_not_start_until_first_keystroke(clock, id_gen):
    start = StartSession(clock=clock, id_gen=id_gen)
    record = RecordKeystroke(clock=clock)
    finish = FinishSession(clock=clock)
    session = start("ab", layout="qwerty", mode=Mode.FREE)

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
