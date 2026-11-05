from __future__ import annotations

import pytest

from keystrike.application.session_use_cases import FinishSession, RecordKeystroke, StartSession
from keystrike.domain.ai_models import AiSettings
from keystrike.domain.enums import Finger, Hand, Mode
from keystrike.domain.models import Layout, Settings
from keystrike.infrastructure.layout_repo import BUNDLED_LAYOUTS
from tests.fakes import (
    FakeAiSettingsRepository,
    FakeClock,
    FakeIdGenerator,
    FakeKeystrokeArchive,
    FakeLayoutRepository,
    FakeSessionRepository,
    FakeSettingsRepository,
)


class _CountingLayouts(FakeLayoutRepository):
    calls: int = 0

    def get(self, name: str) -> Layout:
        self.calls += 1
        return super().get(name)


def _run(
    provider: str,
    archive: FakeKeystrokeArchive,
    *,
    repo: FakeSessionRepository | None = None,
    settings: Settings | None = None,
    session_id: str | None = None,
):
    clock = FakeClock()
    ids = FakeIdGenerator()
    start = StartSession(clock=clock, id_gen=ids)
    layouts = _CountingLayouts(dict(BUNDLED_LAYOUTS))
    record = RecordKeystroke(clock=clock, layout_repo=layouts)
    finish = FinishSession(
        clock=clock,
        repo=repo if repo is not None else FakeSessionRepository(),
        settings_repo=FakeSettingsRepository(settings or Settings()),
        layout_repo=layouts,
        keystroke_archive=archive,
        ai_settings_repo=FakeAiSettingsRepository(AiSettings(provider=provider)),
    )
    session = start("asd", layout="qwerty", mode=Mode.ADAPTIVE)
    if session_id is not None:
        session.id = session_id
    for ch in "asd":
        clock.advance(100_000_000)
        record(session, ch)
    return session, finish, layouts


def test_keystrokes_carry_the_finger_and_hand_from_the_layout():
    session, _finish, _layouts = _run("", FakeKeystrokeArchive())
    keys = [BUNDLED_LAYOUTS["qwerty"].keys[ord(c)] for c in "asd"]
    assert [k.finger for k in session.keystrokes] == [k.finger for k in keys]
    assert [k.hand for k in session.keystrokes] == [k.hand for k in keys]
    assert all(isinstance(k.finger, Finger) and isinstance(k.hand, Hand) for k in keys)


def test_layout_is_resolved_once_not_per_keystroke():
    _session, _finish, layouts = _run("", FakeKeystrokeArchive())
    assert layouts.calls == 1


def test_archive_is_cleared_while_ai_is_disabled():
    archive = FakeKeystrokeArchive()
    archive.save("old", [])
    session, finish, _ = _run("", archive)
    finish(session)
    assert archive.saved == {}


def test_archive_receives_keystrokes_when_ai_is_enabled():
    archive = FakeKeystrokeArchive()
    session, finish, _ = _run("ollama", archive)
    finish(session)
    assert [k.codepoint for k in archive.saved[session.id]] == [ord(c) for c in "asd"]


def test_archive_keeps_only_the_confidence_window():
    archive = FakeKeystrokeArchive()
    repo = FakeSessionRepository()
    settings = Settings(confidence_session_window=2)
    ids: list[str] = []
    for i in range(4):
        sid = f"s{i}"
        session, finish, _ = _run("ollama", archive, repo=repo, settings=settings, session_id=sid)
        session.started_at_wall = float(i)
        finish(session)
        ids.append(sid)
    assert sorted(archive.saved) == ids[-2:]


def test_archive_failure_does_not_lose_the_session():
    archive = FakeKeystrokeArchive(error=OSError("disk full"))
    session, finish, _ = _run("ollama", archive)
    assert finish(session).total_keystrokes == 3


@pytest.mark.parametrize("provider", ["", "ollama"])
def test_finish_result_is_identical_regardless_of_ai(provider: str):
    session, finish, _ = _run(provider, FakeKeystrokeArchive())
    result = finish(session)
    assert result.correct_keystrokes == 3
