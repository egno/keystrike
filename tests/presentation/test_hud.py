import pytest
from textual.app import App
from textual.widgets import Static

from keystrike.domain.daily_learn import compute_daily_learn_budget
from keystrike.domain.enums import Mode
from keystrike.domain.session import Session
from keystrike.presentation.widgets.hud import HUD, _format_hud
from tests.fakes import FakeClock


def _session(typing_started_at_ns: int | None = None) -> Session:
    return Session(
        id="s1",
        target_text="abc",
        layout="qwerty",
        mode=Mode.ADAPTIVE,
        lang="en",
        started_at_wall=0.0,
        started_at_ns=0,
        typing_started_at_ns=typing_started_at_ns,
        focus_key=ord("e"),
    )


def test_hud_omits_goal_when_daily_limit_disabled():
    text = _format_hud(_session(), elapsed_ns=0, daily_budget=None)
    assert "Goal" not in text
    assert "Time" not in text
    assert "Keys" not in text


def test_hud_shows_daily_time_goal():
    budget = compute_daily_learn_budget(
        completed_ns=6 * 60 * 1_000_000_000,
        limit_minutes=10,
    )
    text = _format_hud(_session(), elapsed_ns=0, daily_budget=budget)
    assert "Goal:" in text
    assert "4.0" in text
    assert "/10 min" in text
    assert "Time" not in text
    assert "Keys" not in text


@pytest.mark.asyncio
async def test_hud_wpm_zero_before_first_keystroke():
    clock = FakeClock()
    session = _session(typing_started_at_ns=None)
    app = App()
    async with app.run_test() as pilot:
        await app.mount(HUD(session, clock))
        clock.advance(10_000_000_000)
        app.screen.query_one(HUD).refresh_display()
        await pilot.pause()
        text = str(app.screen.query_one("#hud-text", Static).content)
        assert "WPM: [bold]  0.0[/]" in text
        assert "Time" not in text
