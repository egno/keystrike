from __future__ import annotations

from collections.abc import Sequence

import pytest

from keystrike.application.session_use_cases import FinishSession, RecordKeystroke, StartSession
from keystrike.domain.enums import Finger, Mode
from keystrike.domain.models import Keystroke, Layout, Settings
from keystrike.infrastructure.layout_repo import BUNDLED_LAYOUTS
from tests.fakes import (
    FakeClock,
    FakeIdGenerator,
    FakeLayoutRepository,
    FakeSessionRepository,
    FakeSettingsRepository,
)


class _Archive:
    def __init__(self, error: Exception | None = None) -> None:
        self.saved: dict[str, list[Keystroke]] = {}
        self.error = error

    def save(self, session_id: str, keystrokes: Sequence[Keystroke]) -> None:
        if self.error is not None:
            raise self.error
        self.saved[session_id] = list(keystrokes)


class _CountingLayouts(FakeLayoutRepository):
    calls: int = 0

    def get(self, name: str) -> Layout:
        self.calls += 1
        return super().get(name)


def _run(settings: Settings, archive: _Archive):
    clock = FakeClock()
    start = StartSession(clock=clock, id_gen=FakeIdGenerator())
    layouts = _CountingLayouts(dict(BUNDLED_LAYOUTS))
    record = RecordKeystroke(clock=clock, layout_repo=layouts)
    finish = FinishSession(
        clock=clock,
        repo=FakeSessionRepository(),
        settings_repo=FakeSettingsRepository(settings),
        layout_repo=layouts,
        keystroke_archive=archive,
    )
    session = start("asd", layout="qwerty", mode=Mode.ADAPTIVE)
    for ch in "asd":
        clock.advance(100_000_000)
        record(session, ch)
    return session, finish, layouts


def test_keystrokes_carry_the_finger_from_the_layout():
    session, _finish, _layouts = _run(Settings(), _Archive())
    expected = [BUNDLED_LAYOUTS["qwerty"].keys[ord(c)].finger for c in "asd"]
    assert [k.finger for k in session.keystrokes] == expected
    assert all(isinstance(f, Finger) for f in expected)


def test_layout_is_resolved_once_not_per_keystroke():
    _session, _finish, layouts = _run(Settings(), _Archive())
    assert layouts.calls == 1


def test_archive_is_skipped_while_ai_is_disabled():
    archive = _Archive()
    session, finish, _ = _run(Settings(ai_provider=""), archive)
    finish(session)
    assert archive.saved == {}


def test_archive_receives_keystrokes_when_ai_is_enabled():
    archive = _Archive()
    session, finish, _ = _run(Settings(ai_provider="ollama"), archive)
    finish(session)
    assert [k.codepoint for k in archive.saved[session.id]] == [ord(c) for c in "asd"]


def test_archive_failure_does_not_lose_the_session():
    archive = _Archive(error=OSError("disk full"))
    session, finish, _ = _run(Settings(ai_provider="ollama"), archive)
    assert finish(session).total_keystrokes == 3


@pytest.mark.parametrize("provider", ["", "ollama"])
def test_finish_result_is_identical_regardless_of_ai(provider: str):
    session, finish, _ = _run(Settings(ai_provider=provider), _Archive())
    result = finish(session)
    assert result.correct_keystrokes == 3
