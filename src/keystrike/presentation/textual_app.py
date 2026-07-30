from typing import ClassVar

from textual.app import App
from textual.binding import BindingType

from keystrike.presentation.bindings import QUIT
from keystrike.presentation.screens.home import HomeScreen
from keystrike.presentation.screens.practice import PracticeScreen
from keystrike.presentation.screens.settings import SettingsScreen
from keystrike.presentation.screens.stats import StatsScreen
from keystrike.presentation.services import (
    HomeServices,
    PracticeServices,
    SettingsServices,
    StatsServices,
)

__all__ = [
    "HomeServices",
    "KeystrikeApp",
    "PracticeServices",
    "SettingsServices",
    "StatsServices",
]


class KeystrikeApp(App[None]):
    ENABLE_COMMAND_PALETTE = False
    BINDINGS: ClassVar[list[BindingType]] = [QUIT]

    def __init__(
        self,
        *,
        home: HomeServices,
        practice: PracticeServices,
        stats: StatsServices,
        settings: SettingsServices,
        app_version: str = "",
    ) -> None:
        super().__init__()
        self._home = home
        self._practice = practice
        self._stats = stats
        self._settings = settings
        self._app_version = app_version

    def on_mount(self) -> None:
        self.install_screen(self._build_home(), name="home")
        self.push_screen("home")

    def _build_home(self) -> HomeScreen:
        return HomeScreen(services=self._home, app_version=self._app_version)

    def on_home_screen_start_practice(self, _: HomeScreen.StartPractice) -> None:
        initial = self._practice.prepare_practice()
        if initial is None:
            return

        self.push_screen(PracticeScreen(services=self._practice, initial=initial))

    def on_home_screen_open_stats(self, _: HomeScreen.OpenStats) -> None:
        settings = self._home.settings_repo.load()
        self.push_screen(
            StatsScreen(
                layout=settings.layout,
                services=self._stats,
                current_target_speed_cpm=settings.target_speed_cpm,
                confidence_session_window=settings.confidence_session_window,
            )
        )

    def on_home_screen_open_settings(self, _: HomeScreen.OpenSettings) -> None:
        self.push_screen(SettingsScreen(services=self._settings))

    def action_quit_app(self) -> None:
        self.exit()
