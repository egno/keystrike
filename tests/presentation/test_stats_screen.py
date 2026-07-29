from typing import cast

import pytest
from textual.app import App
from textual.widgets import Static

from keystrike.application.stats_use_cases import GetHeatmap, GetHistory, RebuildAggregates
from keystrike.domain.enums import Mode
from keystrike.domain.models import Keystroke, SessionResult, Settings
from keystrike.infrastructure.layout_repo import BUNDLED_LAYOUTS
from keystrike.presentation.screens.stats import StatsScreen
from tests.fakes import (
    FakeAggregatesCache,
    FakeLayoutRepository,
    FakeSessionRepository,
    FakeSettingsRepository,
)


def _build_screen(
    repo: FakeSessionRepository,
    layout: str = "qwerty",
    *,
    settings: Settings | None = None,
) -> StatsScreen:
    cache = FakeAggregatesCache()
    settings_repo = FakeSettingsRepository(settings or Settings())
    layout_repo = FakeLayoutRepository(dict(BUNDLED_LAYOUTS))
    return StatsScreen(
        layout=layout,
        layout_repo=layout_repo,
        rebuild_aggregates=RebuildAggregates(repo=repo, cache=cache),
        get_heatmap=GetHeatmap(cache=cache, settings_repo=settings_repo),
        get_history=GetHistory(repo=repo),
        current_target_speed_cpm=settings_repo.settings.target_speed_cpm,
    )


@pytest.mark.asyncio
async def test_stats_screen_with_no_sessions_shows_placeholder():
    app = App()
    async with app.run_test() as pilot:
        repo = FakeSessionRepository()
        await app.push_screen(_build_screen(repo))
        await pilot.pause()
        history_text = app.screen.query_one("#stats-history", Static).content
        assert "No sessions yet" in str(history_text)


@pytest.mark.asyncio
async def test_stats_screen_with_sessions_renders_history_and_heatmap():
    app = App()
    async with app.run_test() as pilot:
        repo = FakeSessionRepository()
        header = SessionResult(
            schema_version=1,
            session_id="s1",
            started_at=1_700_000_000.0,
            duration_ns=1_000_000_000,
            layout="qwerty",
            mode=Mode.ADAPTIVE,
            lesson_alphabet=(ord("a"),),
            focus_key=None,
            total_keystrokes=1,
            correct_keystrokes=1,
        )
        repo.save_header(header)
        repo.keystrokes["s1"] = [
            Keystroke(codepoint=ord("a"), typed=ord("a"), t_ns=0, correct=True),
        ]

        await app.push_screen(_build_screen(repo))
        await pilot.pause()

        history_text = str(app.screen.query_one("#stats-history", Static).content)
        assert "wpm" in history_text
        assert app.screen.query_one("#kb-heatmap-text") is not None
        caption = str(app.screen.query_one("#stats-heatmap-caption", Static).content)
        assert "vs current goal" in caption


@pytest.mark.asyncio
async def test_stats_screen_renders_wpm_trend():
    app = App()
    async with app.run_test() as pilot:
        repo = FakeSessionRepository()
        header = SessionResult(
            schema_version=2,
            session_id="s1",
            started_at=1_700_000_000.0,
            duration_ns=60_000_000_000,
            layout="qwerty",
            mode=Mode.ADAPTIVE,
            lesson_alphabet=(ord("a"),),
            focus_key=None,
            total_keystrokes=50,
            correct_keystrokes=50,
        )
        repo.save_header(header)

        await app.push_screen(_build_screen(repo))
        await pilot.pause()

        wpm_text = str(app.screen.query_one("#stats-wpm-trend", Static).content)
        assert "WPM trend" in wpm_text
        assert "latest" in wpm_text


@pytest.mark.asyncio
async def test_stats_screen_renders_focus_confidence_trend():
    app = App()
    async with app.run_test() as pilot:
        repo = FakeSessionRepository()
        header = SessionResult(
            schema_version=3,
            session_id="s1",
            started_at=1_700_000_000.0,
            duration_ns=60_000_000_000,
            layout="qwerty",
            mode=Mode.ADAPTIVE,
            lesson_alphabet=(ord("e"),),
            focus_key=ord("e"),
            total_keystrokes=50,
            correct_keystrokes=50,
            key_confidence={ord("e"): 0.82},
        )
        repo.save_header(header)

        await app.push_screen(_build_screen(repo))
        await pilot.pause()

        focus_text = str(app.screen.query_one("#stats-focus-confidence", Static).content)
        assert "Focus 'e' confidence" in focus_text
        assert "latest" in focus_text


@pytest.mark.asyncio
async def test_stats_title_flags_ortholinear_layout():
    app = App()
    async with app.run_test() as pilot:
        repo = FakeSessionRepository()
        await app.push_screen(_build_screen(repo, layout="colemak_dh"))
        await pilot.pause()
        title = str(app.screen.query_one("#stats-title", Static).content)
        assert "ortholinear" in title


@pytest.mark.asyncio
async def test_stats_title_omits_ortholinear_for_staggered_layout():
    app = App()
    async with app.run_test() as pilot:
        repo = FakeSessionRepository()
        await app.push_screen(_build_screen(repo, layout="qwerty"))
        await pilot.pause()
        title = str(app.screen.query_one("#stats-title", Static).content)
        assert "ortholinear" not in title


def _session_with_key_confidence(
    *,
    session_id: str,
    started_at: float,
    key_confidence: dict[int, float],
    target_speed_cpm: int = 0,
) -> SessionResult:
    return SessionResult(
        schema_version=3,
        session_id=session_id,
        started_at=started_at,
        duration_ns=60_000_000_000,
        layout="qwerty",
        mode=Mode.ADAPTIVE,
        lesson_alphabet=tuple(key_confidence),
        focus_key=next(iter(key_confidence), None),
        total_keystrokes=50,
        correct_keystrokes=50,
        key_confidence=key_confidence,
        target_speed_cpm=target_speed_cpm,
    )


@pytest.mark.asyncio
async def test_stats_key_press_shows_key_detail():
    app = App()
    async with app.run_test() as pilot:
        repo = FakeSessionRepository()
        repo.save_header(_session_with_key_confidence(
            session_id="s1",
            started_at=1.0,
            key_confidence={ord("e"): 0.55},
        ))
        await app.push_screen(_build_screen(repo))
        await pilot.pause()

        await pilot.press("e")
        await pilot.pause()

        screen = cast(StatsScreen, app.screen)
        assert screen._view == "key_detail"
        assert screen._selected_cp == ord("e")
        detail = str(screen.query_one("#stats-key-detail", Static).content)
        assert "'e' confidence" in detail
        assert "cumulative" not in detail
        assert screen.query_one("#stats-wpm-trend", Static).display is False
        assert screen.query_one("#stats-history", Static).display is False


@pytest.mark.asyncio
async def test_stats_key_detail_switches_key_without_overview():
    app = App()
    async with app.run_test() as pilot:
        repo = FakeSessionRepository()
        repo.save_header(_session_with_key_confidence(
            session_id="s1",
            started_at=1.0,
            key_confidence={ord("a"): 0.40, ord("b"): 0.70},
        ))
        await app.push_screen(_build_screen(repo))
        await pilot.pause()

        await pilot.press("a")
        await pilot.pause()
        screen = cast(StatsScreen, app.screen)
        assert screen._view == "key_detail"
        assert screen._selected_cp == ord("a")
        assert "'a' confidence" in str(screen.query_one("#stats-key-detail", Static).content)

        await pilot.press("b")
        await pilot.pause()

        assert screen._view == "key_detail"
        assert screen._selected_cp == ord("b")
        detail = str(screen.query_one("#stats-key-detail", Static).content)
        assert "'b' confidence" in detail
        assert "'a' confidence" not in detail
        assert screen.query_one("#stats-wpm-trend", Static).display is False


@pytest.mark.asyncio
async def test_stats_key_detail_normalizes_confidence_to_current_goal():
    """Key-detail trend rescales stored snapshots to the current goal."""
    app = App()
    async with app.run_test() as pilot:
        repo = FakeSessionRepository()
        repo.save_header(_session_with_key_confidence(
            session_id="s1",
            started_at=1.0,
            key_confidence={ord("e"): 1.0},
            target_speed_cpm=300,
        ))
        await app.push_screen(_build_screen(
            repo,
            settings=Settings(target_speed_cpm=600),
        ))
        await pilot.pause()

        await pilot.press("e")
        await pilot.pause()

        detail = str(app.screen.query_one("#stats-key-detail", Static).content)
        assert "latest 0.50" in detail


@pytest.mark.asyncio
async def test_stats_key_detail_stable_when_goal_changes():
    """Key-detail trend uses frozen snapshots, not live heatmap confidence."""
    app = App()
    async with app.run_test() as pilot:
        repo = FakeSessionRepository()
        repo.save_header(_session_with_key_confidence(
            session_id="s1",
            started_at=1.0,
            key_confidence={ord("e"): 0.82},
        ))
        await app.push_screen(_build_screen(
            repo,
            settings=Settings(target_speed_cpm=600),
        ))
        await pilot.pause()

        await pilot.press("e")
        await pilot.pause()

        detail = str(app.screen.query_one("#stats-key-detail", Static).content)
        assert "latest 0.82" in detail
        assert "cumulative" not in detail


@pytest.mark.asyncio
async def test_stats_escape_from_key_detail_returns_to_overview():
    app = App()
    async with app.run_test() as pilot:
        repo = FakeSessionRepository()
        repo.save_header(_session_with_key_confidence(
            session_id="s1",
            started_at=1.0,
            key_confidence={ord("e"): 0.55},
        ))
        await app.push_screen(_build_screen(repo))
        await pilot.pause()

        await pilot.press("e")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()

        screen = cast(StatsScreen, app.screen)
        assert screen._view == "overview"
        assert screen.query_one("#stats-key-detail", Static).display is False
        assert screen.query_one("#stats-wpm-trend", Static).display is True
        assert "WPM trend" in str(screen.query_one("#stats-wpm-trend", Static).content)


@pytest.mark.asyncio
async def test_stats_escape_in_overview_pops_screen():
    app = App()
    async with app.run_test() as pilot:
        repo = FakeSessionRepository()
        await app.push_screen(_build_screen(repo))
        await pilot.pause()

        await pilot.press("escape")
        await pilot.pause()

        assert not isinstance(app.screen, StatsScreen)


@pytest.mark.asyncio
async def test_stats_ignores_key_not_in_layout():
    app = App()
    async with app.run_test() as pilot:
        repo = FakeSessionRepository()
        await app.push_screen(_build_screen(repo))
        await pilot.pause()

        await pilot.press("!")
        await pilot.pause()

        screen = cast(StatsScreen, app.screen)
        assert screen._view == "overview"
        assert screen.query_one("#stats-key-detail", Static).display is False
