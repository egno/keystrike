import pytest
from textual.app import App
from textual.widgets import Static

from keystrike.application.settings_use_cases import CycleLayout
from keystrike.domain.models import Settings
from keystrike.infrastructure.layout_repo import BUNDLED_LAYOUTS
from keystrike.presentation.screens.home import HomeScreen
from tests.fakes import FakeLayoutRepository, FakeSettingsRepository


def _build_screen(settings: Settings | None = None) -> tuple[HomeScreen, FakeSettingsRepository]:
    settings_repo = FakeSettingsRepository(settings or Settings())
    layout_repo = FakeLayoutRepository(dict(BUNDLED_LAYOUTS))
    cycle_layout = CycleLayout(settings_repo=settings_repo, layout_repo=layout_repo)
    return HomeScreen(settings_repo=settings_repo, cycle_layout=cycle_layout), settings_repo


@pytest.mark.asyncio
async def test_shows_current_layout():
    app = App()
    async with app.run_test() as pilot:
        screen, _ = _build_screen(Settings(layout="dvorak"))
        await app.push_screen(screen)
        await pilot.pause()
        hero = str(app.screen.query_one("#home-hero", Static).content)
        assert "dvorak" in hero


@pytest.mark.asyncio
async def test_cycle_layout_persists_and_updates_display():
    app = App()
    async with app.run_test() as pilot:
        screen, settings_repo = _build_screen(Settings(layout="qwerty"))
        await app.push_screen(screen)
        await pilot.pause()
        await pilot.press("l")
        await pilot.pause()
        assert settings_repo.settings.layout != "qwerty"
        hero = str(app.screen.query_one("#home-hero", Static).content)
        assert settings_repo.settings.layout in hero


@pytest.mark.asyncio
async def test_enter_posts_start_practice_adaptive():
    received: list[str] = []

    class ProbeApp(App[None]):
        def on_home_screen_start_practice(self, message: HomeScreen.StartPractice) -> None:
            received.append(message.source)

    app = ProbeApp()
    async with app.run_test() as pilot:
        screen, _ = _build_screen()
        await app.push_screen(screen)
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert received == ["adaptive"]


@pytest.mark.asyncio
async def test_p_posts_start_practice_sample():
    received: list[str] = []

    class ProbeApp(App[None]):
        def on_home_screen_start_practice(self, message: HomeScreen.StartPractice) -> None:
            received.append(message.source)

    app = ProbeApp()
    async with app.run_test() as pilot:
        screen, _ = _build_screen()
        await app.push_screen(screen)
        await pilot.pause()
        await pilot.press("p")
        await pilot.pause()
        assert received == ["sample"]


@pytest.mark.asyncio
async def test_f_posts_start_practice_free():
    received: list[str] = []

    class ProbeApp(App[None]):
        def on_home_screen_start_practice(self, message: HomeScreen.StartPractice) -> None:
            received.append(message.source)

    app = ProbeApp()
    async with app.run_test() as pilot:
        screen, _ = _build_screen()
        await app.push_screen(screen)
        await pilot.pause()
        await pilot.press("f")
        await pilot.pause()
        assert received == ["free"]


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
