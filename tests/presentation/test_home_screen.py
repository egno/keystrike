import datetime as dt

import pytest
from textual.app import App
from textual.widgets import Static

from keystrike.application.learn_budget_use_cases import GetDailyLearnBudget
from keystrike.application.settings_use_cases import CycleLayout
from keystrike.domain.enums import Mode
from keystrike.domain.models import SessionResult, Settings
from keystrike.infrastructure.layout_repo import BUNDLED_LAYOUTS
from keystrike.presentation.screens.home import HomeScreen
from tests.fakes import (
    FakeClock,
    FakeLayoutRepository,
    FakeSessionRepository,
    FakeSettingsRepository,
)

_TZ = dt.timezone(dt.timedelta(hours=3))


def _build_screen(
    *,
    settings: Settings | None = None,
    headers: list[SessionResult] | None = None,
    wall: float | None = None,
) -> tuple[HomeScreen, FakeSettingsRepository]:
    clock = FakeClock(wall=wall or dt.datetime(2026, 7, 28, 12, 0, tzinfo=_TZ).timestamp())
    settings_repo = FakeSettingsRepository(settings or Settings())
    session_repo = FakeSessionRepository(headers=headers or [])
    layout_repo = FakeLayoutRepository(dict(BUNDLED_LAYOUTS))
    cycle_layout = CycleLayout(settings_repo=settings_repo, layout_repo=layout_repo)
    get_daily_learn_budget = GetDailyLearnBudget(
        clock=clock,
        repo=session_repo,
        settings_repo=settings_repo,
        tz=_TZ,
    )
    return (
        HomeScreen(
            settings_repo=settings_repo,
            cycle_layout=cycle_layout,
            get_daily_learn_budget=get_daily_learn_budget,
        ),
        settings_repo,
    )


@pytest.mark.asyncio
async def test_shows_daily_learn_budget():

    noon = dt.datetime(2026, 7, 28, 12, 0, tzinfo=_TZ).timestamp()
    header = SessionResult(
        schema_version=1,
        session_id="s1",
        started_at=noon,
        duration_ns=6 * 60 * 1_000_000_000,
        layout="qwerty",
        mode=Mode.ADAPTIVE,
        lesson_alphabet=(),
        focus_key=ord("e"),
        total_keystrokes=1,
        correct_keystrokes=1,
    )
    app = App()
    async with app.run_test() as pilot:
        screen, _ = _build_screen(headers=[header])
        await app.push_screen(screen)
        await pilot.pause()
        hero = str(app.screen.query_one("#home-hero", Static).content)
        assert "Learn today:" in hero
        assert "6.0" in hero
        assert "left" not in hero


@pytest.mark.asyncio
async def test_shows_daily_learn_goal_reached():

    noon = dt.datetime(2026, 7, 28, 12, 0, tzinfo=_TZ).timestamp()
    header = SessionResult(
        schema_version=1,
        session_id="s1",
        started_at=noon,
        duration_ns=10 * 60 * 1_000_000_000,
        layout="qwerty",
        mode=Mode.ADAPTIVE,
        lesson_alphabet=(),
        focus_key=ord("e"),
        total_keystrokes=1,
        correct_keystrokes=1,
    )
    app = App()
    async with app.run_test() as pilot:
        screen, _ = _build_screen(headers=[header])
        await app.push_screen(screen)
        await pilot.pause()
        hero = str(app.screen.query_one("#home-hero", Static).content)
        assert "Learn today:" in hero
        assert "10.0" in hero
        assert "/10 min" in hero


@pytest.mark.asyncio
async def test_shows_current_layout():
    app = App()
    async with app.run_test() as pilot:
        screen, _ = _build_screen(settings=Settings(layout="dvorak"))
        await app.push_screen(screen)
        await pilot.pause()
        hero = str(app.screen.query_one("#home-hero", Static).content)
        assert "dvorak" in hero


@pytest.mark.asyncio
async def test_cycle_layout_persists_and_updates_display():
    app = App()
    async with app.run_test() as pilot:
        screen, settings_repo = _build_screen(settings=Settings(layout="qwerty"))
        await app.push_screen(screen)
        await pilot.pause()
        await pilot.press("l")
        await pilot.pause()
        assert settings_repo.settings.layout != "qwerty"
        hero = str(app.screen.query_one("#home-hero", Static).content)
        assert settings_repo.settings.layout in hero


@pytest.mark.asyncio
async def test_enter_posts_start_practice():
    received: list[bool] = []

    class ProbeApp(App[None]):
        def on_home_screen_start_practice(self, _: HomeScreen.StartPractice) -> None:
            received.append(True)

    app = ProbeApp()
    async with app.run_test() as pilot:
        screen, _ = _build_screen()
        await app.push_screen(screen)
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert received == [True]


@pytest.mark.asyncio
async def test_s_posts_open_stats():
    received = []

    class ProbeApp(App[None]):
        def on_home_screen_open_stats(self, message: HomeScreen.OpenStats) -> None:
            received.append(message)

    app = ProbeApp()
    async with app.run_test() as pilot:
        screen, _ = _build_screen()
        await app.push_screen(screen)
        await pilot.pause()
        await pilot.press("s")
        await pilot.pause()
        assert len(received) == 1


@pytest.mark.asyncio
async def test_o_posts_open_settings():
    received = []

    class ProbeApp(App[None]):
        def on_home_screen_open_settings(self, message: HomeScreen.OpenSettings) -> None:
            received.append(message)

    app = ProbeApp()
    async with app.run_test() as pilot:
        screen, _ = _build_screen()
        await app.push_screen(screen)
        await pilot.pause()
        await pilot.press("o")
        await pilot.pause()
        assert len(received) == 1
