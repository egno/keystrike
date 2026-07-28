import pytest
from textual.app import App
from textual.widgets import Static

from keystrike.domain.daily_learn import compute_daily_learn_budget
from keystrike.domain.enums import Mode
from keystrike.domain.session import Session
from keystrike.presentation.widgets.hud import HUD, _format_hud
from tests.fakes import FakeClock

_UNLIMITED = compute_daily_learn_budget(completed_ns=0, limit_minutes=0)


def _session(
    *,
    correct: int = 0,
    total: int = 0,
    typing_started_at_ns: int | None = None,
) -> Session:
    session = Session(
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
    session.correct_count = correct
    session.total_count = total
    return session


def test_hud_shows_accuracy_without_wpm():
    text = _format_hud(_session(correct=8, total=10), _UNLIMITED)
    assert text.startswith("Acc: [bold] 80.0%[/]")
    assert "WPM" not in text


def test_hud_omits_daily_goal_when_limit_disabled():
    session = Session(
        id="s1",
        target_text="abc",
        layout="qwerty",
        mode=Mode.ADAPTIVE,
        lang="en",
        started_at_wall=0.0,
        started_at_ns=0,
    )
    text = _format_hud(session, _UNLIMITED)
    assert "Learn:" not in text


def test_hud_shows_sessions_to_goal_for_focus_key():
    text = _format_hud(_session(), _UNLIMITED, sessions_to_goal=3)
    assert "Sessions[e]: ~3 sessions" in text


def test_hud_shows_learning_when_sessions_to_goal_unknown():
    text = _format_hud(_session(), _UNLIMITED, sessions_to_goal=None)
    assert "Sessions[e]: learning…" in text


def test_hud_shows_focus_reason_when_given():
    text = _format_hud(_session(), _UNLIMITED, focus_reason="review")
    assert "Focus:" in text
    assert "review" in text


def test_hud_omits_focus_when_reason_missing():
    text = _format_hud(_session(), _UNLIMITED, focus_reason=None)
    assert "Focus:" not in text


def test_hud_shows_daily_learn_goal_when_limited():
    budget = compute_daily_learn_budget(
        completed_ns=6 * 60 * 1_000_000_000,
        limit_minutes=10,
    )
    text = _format_hud(_session(), budget)
    assert "Learn:" in text
    assert "4.0" in text
    assert "/10 min" in text
    assert "WPM" not in text


def test_hud_distinct_labels_for_daily_budget_sessions_and_focus():
    budget = compute_daily_learn_budget(
        completed_ns=9 * 60 * 1_000_000_000,
        limit_minutes=10,
    )
    session = _session()
    session.focus_key = ord("s")
    text = _format_hud(
        session,
        budget,
        focus_reason="weak",
        sessions_to_goal=0,
    )
    assert "Learn:" in text
    assert "1.0" in text
    assert "/10 min" in text
    assert "Sessions[s]: done" in text
    assert "Focus:" in text
    assert "weak" in text
    assert text.count("Goal:") == 0


@pytest.mark.asyncio
async def test_hud_accuracy_updates_on_refresh():
    clock = FakeClock()
    session = _session(correct=1, total=2)
    app = App()
    async with app.run_test() as pilot:
        await app.mount(HUD(session, clock))
        app.screen.query_one(HUD).refresh_display()
        await pilot.pause()
        text = str(app.screen.query_one("#hud-text", Static).content)
        assert "50.0%" in text
        assert "WPM" not in text
