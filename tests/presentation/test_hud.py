import pytest
from textual.app import App
from textual.widgets import Static

from keystrike.domain.confidence import FocusReason
from keystrike.domain.daily_learn import compute_daily_learn_budget
from keystrike.domain.enums import FocusKind, Mode
from keystrike.domain.models import Bigram
from keystrike.domain.session import (
    LEARN_IDLE_PAUSE_NS,
    Session,
    active_typing_duration_ns,
    is_typing_idle,
)
from keystrike.presentation.widgets.hud import HUD, _format_hud, learn_timer_dimmed
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


def _active_session(**kwargs) -> Session:
    session = _session(typing_started_at_ns=0, **kwargs)
    session.last_keystroke_at_ns = 0
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
    assert "eo weak transition" in text


def test_hud_shows_focus_reason_when_given():
    reason = FocusReason(kind=FocusKind.KEY_REVIEW)
    text = _format_hud(_session(), _UNLIMITED, focus_reason=reason)
    assert "Focus:" in text
    assert "review" in text


def test_hud_shows_single_key_focus_for_non_transition():
    session = _session()
    session.focus_key = ord("a")
    reason = FocusReason(kind=FocusKind.KEY_WEAK)
    text = _format_hud(session, _UNLIMITED, focus_reason=reason)
    assert "[bold]a[/]" in text


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
    text = _format_hud(_active_session(), budget, dim_learn=False)
    assert "Learn:" in text
    assert "10.0" in text
    assert "/10 min" in text
    assert "[green]   Learn: [bold]10.0[/]/10 min[/]" in text


def test_hud_learn_segment_green_when_goal_reached_and_active():
    budget = compute_daily_learn_budget(
        completed_ns=10 * 60 * 1_000_000_000,
        limit_minutes=10,
    )
    text = _format_hud(_active_session(), budget, dim_learn=False)
    assert "[green]   Learn: [bold]10.0[/]/10 min[/]" in text
    assert "[dim]   Learn:" not in text


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


def test_hud_learn_timer_excludes_idle_beyond_pause():
    clock = FakeClock()
    session = _session(typing_started_at_ns=0)
    session.last_keystroke_at_ns = 2_000_000_000
    session.active_duration_ns = 2_000_000_000
    clock.advance(12_000_000_000)  # 10s since last key; only 5s grace counts

    assert active_typing_duration_ns(session, clock.now_ns()) == 7_000_000_000
    assert LEARN_IDLE_PAUSE_NS == 5_000_000_000


def test_hud_learn_segment_dimmed_before_first_keystroke():
    budget = compute_daily_learn_budget(
        completed_ns=6 * 60 * 1_000_000_000,
        limit_minutes=10,
    )
    text = _format_hud(_session(), budget)
    assert "[dim]   Learn: [bold]6.0[/]/10 min[/]" in text


def test_hud_learn_segment_undimmed_while_actively_typing():
    budget = compute_daily_learn_budget(
        completed_ns=6 * 60 * 1_000_000_000,
        limit_minutes=10,
    )
    text = _format_hud(_active_session(), budget, dim_learn=False)
    assert "[dim]   Learn:" not in text
    assert "   Learn: [bold]6.0[/]/10 min" in text


def test_hud_learn_segment_dimmed_while_idle():
    budget = compute_daily_learn_budget(
        completed_ns=6 * 60 * 1_000_000_000,
        limit_minutes=10,
    )
    session = _active_session()
    session.last_keystroke_at_ns = 0
    clock = FakeClock()
    clock.advance(LEARN_IDLE_PAUSE_NS)
    assert is_typing_idle(session, clock.now_ns())
    text = _format_hud(session, budget, dim_learn=learn_timer_dimmed(session, clock.now_ns()))
    assert "[dim]   Learn: [bold]6.0[/]/10 min[/]" in text


def test_hud_learn_segment_dim_green_when_goal_reached_but_idle():
    budget = compute_daily_learn_budget(
        completed_ns=10 * 60 * 1_000_000_000,
        limit_minutes=10,
    )
    session = _active_session()
    session.last_keystroke_at_ns = 0
    clock = FakeClock()
    clock.advance(LEARN_IDLE_PAUSE_NS)
    text = _format_hud(session, budget, dim_learn=learn_timer_dimmed(session, clock.now_ns()))
    assert "[dim][green]   Learn: [bold]10.0[/]/10 min[/][/]" in text
