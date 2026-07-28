import pytest
from textual.app import App
from textual.widgets import Static

from keystrike.domain.enums import Mode
from keystrike.domain.session import Session
from keystrike.presentation.widgets.hud import HUD, _format_hud
from tests.fakes import FakeClock


def _session(focus_key: int | None, typing_started_at_ns: int | None = None) -> Session:
    return Session(
        id="s1",
        target_text="abc",
        layout="qwerty",
        mode=Mode.ADAPTIVE,
        lang="en",
        started_at_wall=0.0,
        started_at_ns=0,
        typing_started_at_ns=typing_started_at_ns,
        focus_key=focus_key,
    )


def test_hud_omits_goal_segment_without_focus_key():
    text = _format_hud(_session(focus_key=None), elapsed_ns=0, sessions_to_goal=None)
    assert "Goal" not in text


def test_hud_shows_learning_when_no_estimate_yet():
    text = _format_hud(_session(focus_key=ord("e")), elapsed_ns=0, sessions_to_goal=None)
    assert "Goal[e]" in text
    assert "learning…" in text


def test_hud_shows_sessions_to_goal_estimate():
    text = _format_hud(_session(focus_key=ord("e")), elapsed_ns=0, sessions_to_goal=3)
    assert "Goal[e]" in text
    assert "~3 sessions" in text


@pytest.mark.asyncio
async def test_hud_time_stays_zero_before_first_keystroke():
    clock = FakeClock()
    session = _session(focus_key=None, typing_started_at_ns=None)
    app = App()
    async with app.run_test() as pilot:
        await app.mount(HUD(session, clock))
        clock.advance(10_000_000_000)  # 10s of "thinking time"
        app.screen.query_one(HUD).refresh_display()
        await pilot.pause()
        text = str(app.screen.query_one("#hud-text", Static).content)
        assert "Time: [bold]  0.0s[/]" in text


@pytest.mark.asyncio
async def test_hud_time_starts_at_first_keystroke():
    clock = FakeClock()
    session = _session(focus_key=None, typing_started_at_ns=None)
    app = App()
    async with app.run_test() as pilot:
        await app.mount(HUD(session, clock))
        clock.advance(10_000_000_000)
        session.typing_started_at_ns = clock.now_ns()  # first keystroke lands here
        clock.advance(2_000_000_000)
        app.screen.query_one(HUD).refresh_display()
        await pilot.pause()
        text = str(app.screen.query_one("#hud-text", Static).content)
        assert "Time: [bold]  2.0s[/]" in text
