from typing import cast

import pytest
from textual.app import App
from textual.containers import Vertical
from textual.widgets import Static

from keystrike.application.stats_use_cases import (
    GetAggregateMetricTrends,
    GetHeatmap,
    GetHistory,
    GetKeyMetricTrends,
    RebuildAggregates,
)
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
        rebuild_aggregates=RebuildAggregates(
            repo=repo, cache=cache, settings_repo=settings_repo,
        ),
        get_heatmap=GetHeatmap(cache=cache, settings_repo=settings_repo),
        get_history=GetHistory(repo=repo),
        get_key_metric_trends=GetKeyMetricTrends(
            repo=repo,
            settings_repo=settings_repo,
        ),
        get_aggregate_metric_trends=GetAggregateMetricTrends(
            repo=repo,
            settings_repo=settings_repo,
        ),
        current_target_speed_cpm=settings_repo.settings.target_speed_cpm,
        confidence_session_window=settings_repo.settings.confidence_session_window,
    )


@pytest.mark.asyncio
async def test_stats_screen_widget_order():
    app = App()
    async with app.run_test() as pilot:
        repo = FakeSessionRepository()
        await app.push_screen(_build_screen(repo))
        await pilot.pause()

        vertical = app.screen.query_one(Vertical)
        widget_ids = [
            w.id for w in vertical.children
            if getattr(w, "id", None) is not None
        ]
        assert widget_ids == [
            "stats-title",
            "stats-trends",
            "stats-heatmap-caption",
            "stats-heatmap-hint",
        ]


@pytest.mark.asyncio
async def test_stats_overview_focus_shows_confidence_only():
    app = App()
    async with app.run_test() as pilot:
        repo = FakeSessionRepository()
        header = SessionResult(
            schema_version=3,
            session_id="s1",
            started_at=1.0,
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
        repo.keystrokes["s1"] = [
            Keystroke(codepoint=ord("e"), typed=ord("e"), t_ns=0, correct=True),
            Keystroke(
                codepoint=ord("e"), typed=ord("e"), t_ns=400_000_000, correct=True,
            ),
        ]

        await app.push_screen(_build_screen(repo))
        await pilot.pause()

        focus_text = str(app.screen.query_one("#stats-trends", Static).content)
        assert "[bold]Focus 'e'[/]" in focus_text
        assert "Layout" in focus_text
        layout_section, focus_section = focus_text.split("\n\n", 1)
        assert "[bold cyan]confidence[/]" in layout_section
        assert "[bold green]speed     [/]" in layout_section
        assert "[bold yellow]accuracy  [/]" in layout_section
        assert "[bold cyan]confidence[/]" in focus_section
        assert "[bold green]speed     [/]" not in focus_section
        assert "[bold yellow]accuracy  [/]" not in focus_section


@pytest.mark.asyncio
async def test_stats_screen_with_no_sessions_shows_placeholder():
    app = App()
    async with app.run_test() as pilot:
        repo = FakeSessionRepository()
        await app.push_screen(_build_screen(repo))
        await pilot.pause()
        trends_text = app.screen.query_one("#stats-trends", Static).content
        assert "No sessions yet" in str(trends_text)


@pytest.mark.asyncio
async def test_stats_screen_with_sessions_renders_trends_and_heatmap():
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

        trends_text = str(app.screen.query_one("#stats-trends", Static).content)
        assert "Layout" in trends_text
        assert app.screen.query_one("#kb-heatmap-text") is not None
        caption = str(app.screen.query_one("#stats-heatmap-caption", Static).content)
        assert "vs current goal" in caption
        hint = str(app.screen.query_one("#stats-heatmap-hint", Static).content)
        assert "Press a key on the heatmap for letter stats" in hint
        assert "Esc to return" in hint


@pytest.mark.asyncio
async def test_stats_trends_uses_confidence_session_window():
    app = App()
    async with app.run_test() as pilot:
        repo = FakeSessionRepository()
        window = 3
        for i in range(window + 2):
            repo.save_header(SessionResult(
                schema_version=2,
                session_id=f"s{i}",
                started_at=float(i),
                duration_ns=60_000_000_000,
                layout="qwerty",
                mode=Mode.ADAPTIVE,
                lesson_alphabet=(ord("a"),),
                focus_key=None,
                total_keystrokes=50,
                correct_keystrokes=50,
            ))

        await app.push_screen(_build_screen(
            repo,
            settings=Settings(confidence_session_window=window),
        ))
        await pilot.pause()

        trends_text = str(app.screen.query_one("#stats-trends", Static).content)
        assert f"({window} sessions)" in trends_text


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

        focus_text = str(app.screen.query_one("#stats-trends", Static).content)
        assert "[bold]Focus 'e'[/]" in focus_text
        assert "[bold cyan]confidence[/]" in focus_text
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
        detail = str(screen.query_one("#stats-trends", Static).content)
        assert "[bold]'e'[/]" in detail
        assert "confidence" in detail
        assert "speed" in detail
        assert "accuracy" in detail
        assert "'e' confidence" not in detail
        assert "'e' speed" not in detail
        assert "'e' accuracy" not in detail
        assert detail.count("sessions") == 1
        assert "[bold green]speed     [/]" in detail
        assert "[bold yellow]accuracy  [/]" in detail
        assert "[cyan]" in detail
        assert "[green]" in detail
        assert "[yellow]" in detail
        assert "cumulative" not in detail
        assert "Layout" not in detail
        assert "Focus" not in detail


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
        assert "[bold]'a'[/]" in str(screen.query_one("#stats-trends", Static).content)

        await pilot.press("b")
        await pilot.pause()

        assert screen._view == "key_detail"
        assert screen._selected_cp == ord("b")
        detail = str(screen.query_one("#stats-trends", Static).content)
        assert "[bold]'b'[/]" in detail
        assert "confidence" in detail
        assert "[bold]'a'[/]" not in detail
        assert "'b' confidence" not in detail


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

        detail = str(app.screen.query_one("#stats-trends", Static).content)
        assert "latest     0.50" in detail


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

        detail = str(app.screen.query_one("#stats-trends", Static).content)
        assert "latest     0.82" in detail
        assert "cumulative" not in detail
        assert detail.count("sessions") == 1


@pytest.mark.asyncio
async def test_stats_key_detail_shows_speed_and_accuracy_trends():
    app = App()
    async with app.run_test() as pilot:
        repo = FakeSessionRepository()
        repo.save_header(_session_with_key_confidence(
            session_id="s1",
            started_at=1.0,
            key_confidence={ord("e"): 0.55},
        ))
        repo.keystrokes["s1"] = [
            Keystroke(codepoint=ord("e"), typed=ord("e"), t_ns=0, correct=True),
            Keystroke(
                codepoint=ord("e"), typed=ord("e"), t_ns=400_000_000, correct=True,
            ),
        ]
        await app.push_screen(_build_screen(repo))
        await pilot.pause()

        await pilot.press("e")
        await pilot.pause()

        detail = str(app.screen.query_one("#stats-trends", Static).content)
        assert "speed" in detail
        assert "accuracy" in detail
        assert "[green]" in detail
        assert "[yellow]" in detail
        assert "latest" in detail


@pytest.mark.asyncio
async def test_stats_screen_renders_speed_and_accuracy_trends():
    app = App()
    async with app.run_test() as pilot:
        repo = FakeSessionRepository()
        header = SessionResult(
            schema_version=3,
            session_id="s1",
            started_at=1.0,
            duration_ns=60_000_000_000,
            layout="qwerty",
            mode=Mode.ADAPTIVE,
            lesson_alphabet=(ord("a"),),
            focus_key=ord("a"),
            total_keystrokes=50,
            correct_keystrokes=50,
            key_confidence={ord("a"): 0.82},
        )
        repo.save_header(header)
        repo.keystrokes["s1"] = [
            Keystroke(codepoint=ord("a"), typed=ord("a"), t_ns=0, correct=True),
            Keystroke(
                codepoint=ord("a"), typed=ord("a"), t_ns=400_000_000, correct=True,
            ),
        ]

        await app.push_screen(_build_screen(repo))
        await pilot.pause()

        metric_text = str(app.screen.query_one("#stats-trends", Static).content)
        assert "[bold]Layout[/]" in metric_text
        layout_section = metric_text.split("\n\n", 1)[0]
        assert "(1 sessions)" in layout_section
        assert layout_section.count("sessions") == 1
        assert "[bold cyan]confidence[/]" in metric_text
        assert "[bold green]speed     [/]" in metric_text
        assert "[bold yellow]accuracy  [/]" in metric_text
        assert "[cyan]" in metric_text
        assert "[green]" in metric_text
        assert "[yellow]" in metric_text
        assert "latest" in metric_text


@pytest.mark.asyncio
async def test_stats_key_press_replaces_overview_trends():
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
        trends = str(screen.query_one("#stats-trends", Static).content)
        assert "[bold]'e'[/]" in trends
        assert "Layout" not in trends


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
        trends = str(screen.query_one("#stats-trends", Static).content)
        assert "Layout" in trends
        assert "[bold]'e'[/]" not in trends


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
        assert "[bold]'e'[/]" not in str(screen.query_one("#stats-trends", Static).content)
