import pytest
from textual.app import App
from textual.widgets import Static

from keystrike.application.stats_use_cases import GetHeatmap, GetHistory, RebuildAggregates
from keystrike.domain.enums import Mode
from keystrike.domain.models import Keystroke, SessionResult
from keystrike.infrastructure.layout_repo import BUNDLED_LAYOUTS
from keystrike.presentation.screens.stats import StatsScreen
from tests.fakes import (
    FakeAggregatesCache,
    FakeLayoutRepository,
    FakeSessionRepository,
    FakeSettingsRepository,
)


def _build_screen(repo: FakeSessionRepository, layout: str = "qwerty") -> StatsScreen:
    cache = FakeAggregatesCache()
    settings_repo = FakeSettingsRepository()
    layout_repo = FakeLayoutRepository(dict(BUNDLED_LAYOUTS))
    return StatsScreen(
        layout=layout,
        layout_repo=layout_repo,
        rebuild_aggregates=RebuildAggregates(repo=repo, cache=cache),
        get_heatmap=GetHeatmap(cache=cache, settings_repo=settings_repo),
        get_history=GetHistory(repo=repo),
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
            mode=Mode.FREE,
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
