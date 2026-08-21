import pytest
from textual.app import App
from textual.widgets import Static

from keystrike.domain.daily_learn import compute_daily_learn_budget
from keystrike.domain.enums import FocusKind, Mode
from keystrike.domain.focus import FocusReason
from keystrike.domain.models import Bigram
from keystrike.domain.session import Session
from keystrike.presentation.widgets.hud import HUD, _format_hud

_UNLIMITED = compute_daily_learn_budget(completed_ns=0, limit_minutes=0)


def _session(
    *,
    correct: int = 0,
    total: int = 0,
) -> Session:
    session = Session(
        id="s1",
        target_text="abc",
        layout="qwerty",
        mode=Mode.ADAPTIVE,
        lang="en",
        started_at_wall=0.0,
        started_at_ns=0,
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


def test_hud_shows_transition_pair_in_focus_label():
    session = _session()
    session.focus_key = ord("o")
    reason = FocusReason(kind=FocusKind.TRANSITION_WEAK, pair=Bigram(ord("e"), ord("o")))
    text = _format_hud(session, _UNLIMITED, focus_reason=reason)
    assert "Focus:" in text
    assert "[bold]eo[/]" in text
    assert "[bold]o[/]" not in text
    assert "· [dim]wk[/]" in text


def test_hud_shows_focus_reason_when_given():
    reason = FocusReason(kind=FocusKind.KEY_REVIEW)
    text = _format_hud(_session(), _UNLIMITED, focus_reason=reason)
    assert "Focus:" in text
    assert "rev" in text


def test_hud_shows_single_key_focus_for_non_transition():
    session = _session()
    session.focus_key = ord("a")
    reason = FocusReason(kind=FocusKind.KEY_WEAK)
    text = _format_hud(session, _UNLIMITED, focus_reason=reason)
    assert "[bold]a[/]" in text


def test_hud_shows_calibrating_focus_reason():
    reason = FocusReason(kind=FocusKind.KEY_CALIBRATING)
    text = _format_hud(_session(), _UNLIMITED, focus_reason=reason)
    assert "Focus:" in text
    assert "cal" in text
    assert "wk" not in text


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
    assert "6.0" in text
    assert "/10 min" in text
    assert "left" not in text
    assert "WPM" not in text


def test_hud_shows_daily_learn_goal_reached():
    budget = compute_daily_learn_budget(
        completed_ns=10 * 60 * 1_000_000_000,
        limit_minutes=10,
    )
    text = _format_hud(_session(), budget)
    assert "Learn:" in text
    assert "10.0" in text
    assert "/10 min" in text
    assert "[green]   Learn: [bold]10.0[/]/10 min[/]" in text


def test_hud_distinct_labels_for_daily_budget_and_focus():
    budget = compute_daily_learn_budget(
        completed_ns=9 * 60 * 1_000_000_000,
        limit_minutes=10,
    )
    session = _session()
    session.focus_key = ord("s")
    text = _format_hud(
        session,
        budget,
        focus_reason=FocusReason(kind=FocusKind.KEY_WEAK),
    )
    assert "Learn:" in text
    assert "9.0" in text
    assert "/10 min" in text
    assert "left" not in text
    assert "Focus:" in text
    assert "wk" in text
    assert text.count("Goal:") == 0


@pytest.mark.asyncio
async def test_hud_reflects_session_passed_at_construction():
    session = _session(correct=1, total=2)
    app = App()
    async with app.run_test():
        await app.mount(HUD(session))
        text = str(app.screen.query_one("#hud-text", Static).content)
        assert "50.0%" in text
        assert "WPM" not in text


@pytest.mark.asyncio
async def test_hud_only_updates_via_set_session():
    session = _session(correct=1, total=2)
    app = App()
    async with app.run_test() as pilot:
        hud = HUD(session)
        await app.mount(hud)
        session.correct_count = 2
        session.total_count = 2
        await pilot.pause()
        text = str(app.screen.query_one("#hud-text", Static).content)
        assert "50.0%" in text  # mutating the session in place doesn't refresh the HUD

        next_session = _session(correct=2, total=2)
        hud.set_session(next_session)
        await pilot.pause()
        text = str(app.screen.query_one("#hud-text", Static).content)
        assert "100.0%" in text
