import pytest
from textual.app import App
from textual.widgets import Input, Select

from keystrike.application.settings_use_cases import UpdateSettings
from keystrike.domain.models import Settings
from keystrike.infrastructure.layout_repo import BUNDLED_LAYOUTS
from keystrike.presentation.screens.settings import SettingsScreen
from tests.fakes import FakeLayoutRepository, FakeSettingsRepository


def _build_screen():
    settings_repo = FakeSettingsRepository(Settings())
    layout_repo = FakeLayoutRepository(dict(BUNDLED_LAYOUTS))
    update_settings = UpdateSettings(repo=settings_repo)
    screen = SettingsScreen(
        settings_repo=settings_repo,
        layout_repo=layout_repo,
        update_settings=update_settings,
    )
    return screen, settings_repo


@pytest.mark.asyncio
async def test_save_persists_changes_and_pops_screen():
    app = App()
    async with app.run_test() as pilot:
        screen, settings_repo = _build_screen()
        await app.push_screen(screen)
        await pilot.pause()

        app.screen.query_one("#settings-speed", Input).value = "400"
        app.screen.query_one("#settings-freeform-path", Input).value = "/tmp/practice.txt"
        app.screen.query_one("#settings-layout", Select).value = "dvorak"
        app.screen.query_one("#settings-alphabet-size", Input).value = "20"
        await pilot.pause()

        await pilot.press("ctrl+s")
        await pilot.pause()

        assert settings_repo.settings.target_speed_cpm == 400
        assert settings_repo.settings.freeform_path == "/tmp/practice.txt"
        assert settings_repo.settings.layout == "dvorak"
        assert settings_repo.settings.alphabet_size == 20
        assert app.screen_stack[-1] is not screen


@pytest.mark.asyncio
async def test_save_rejects_non_integer_speed():
    app = App()
    async with app.run_test() as pilot:
        screen, settings_repo = _build_screen()
        await app.push_screen(screen)
        await pilot.pause()

        app.screen.query_one("#settings-speed", Input).value = "not-a-number"
        await pilot.pause()
        await pilot.press("ctrl+s")
        await pilot.pause()

        assert settings_repo.settings.target_speed_cpm == Settings().target_speed_cpm
        assert app.screen_stack[-1] is screen


@pytest.mark.asyncio
async def test_save_rejects_non_positive_speed():
    app = App()
    async with app.run_test() as pilot:
        screen, settings_repo = _build_screen()
        await app.push_screen(screen)
        await pilot.pause()

        app.screen.query_one("#settings-speed", Input).value = "0"
        await pilot.pause()
        await pilot.press("ctrl+s")
        await pilot.pause()

        assert settings_repo.settings.target_speed_cpm == Settings().target_speed_cpm
        assert app.screen_stack[-1] is screen


@pytest.mark.asyncio
async def test_save_rejects_negative_alphabet_size():
    app = App()
    async with app.run_test() as pilot:
        screen, settings_repo = _build_screen()
        await app.push_screen(screen)
        await pilot.pause()

        app.screen.query_one("#settings-alphabet-size", Input).value = "-1"
        await pilot.pause()
        await pilot.press("ctrl+s")
        await pilot.pause()

        assert settings_repo.settings.alphabet_size == Settings().alphabet_size
        assert app.screen_stack[-1] is screen


@pytest.mark.asyncio
async def test_cancel_discards_changes():
    app = App()
    async with app.run_test() as pilot:
        screen, settings_repo = _build_screen()
        await app.push_screen(screen)
        await pilot.pause()

        app.screen.query_one("#settings-speed", Input).value = "999"
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()

        assert settings_repo.settings.target_speed_cpm == Settings().target_speed_cpm
        assert app.screen_stack[-1] is not screen
