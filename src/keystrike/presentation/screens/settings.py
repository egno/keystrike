from typing import ClassVar, cast

from textual.app import ComposeResult
from textual.binding import BindingType
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Footer, Input, Label, Select, Static
from textual.widgets.select import NoSelection

from keystrike.application.settings_use_cases import SettingsValidationError, UpdateSettings
from keystrike.domain.enums import TargetSpeedUnit
from keystrike.domain.generator import cpm_from_wpm, wpm_from_cpm
from keystrike.domain.protocols import LayoutRepository, SettingsRepository
from keystrike.presentation.bindings import BACK_BINDINGS, SAVE


class SettingsScreen(Screen[None]):
    DEFAULT_CSS = """
    SettingsScreen > Vertical {
        padding: 1 2;
        width: 60;
    }
    SettingsScreen Label {
        margin-top: 1;
    }
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        SAVE,
        *BACK_BINDINGS,
    ]

    def __init__(
        self,
        *,
        settings_repo: SettingsRepository,
        layout_repo: LayoutRepository,
        update_settings: UpdateSettings,
    ) -> None:
        super().__init__()
        self._settings_repo = settings_repo
        self._layout_repo = layout_repo
        self._update_settings = update_settings

    def compose(self) -> ComposeResult:
        settings = self._settings_repo.load()
        layouts = [(name, name) for name in self._layout_repo.list_available()]
        with Vertical():
            yield Static("[bold]Settings[/]  [dim](Ctrl+S save, Esc/q back)[/]")
            yield Label("Layout")
            yield Select(layouts, value=settings.layout, id="settings-layout", allow_blank=False)
            yield Label("Target speed")
            yield Input(
                value=str(
                    wpm_from_cpm(settings.target_speed_cpm)
                    if settings.target_speed_unit == TargetSpeedUnit.WPM
                    else settings.target_speed_cpm
                ),
                id="settings-speed",
                type="integer",
            )
            yield Select(
                [
                    ("WPM (words/min)", TargetSpeedUnit.WPM),
                    ("CPM (chars/min)", TargetSpeedUnit.CPM),
                ],
                value=settings.target_speed_unit,
                id="settings-speed-unit",
                allow_blank=False,
            )
            yield Label("Number of letters unlocked up front")
            yield Input(
                value=str(settings.alphabet_size),
                id="settings-alphabet-size",
                type="integer",
            )
            yield Label("Daily learn limit (minutes; 0 = unlimited)")
            yield Input(
                value=str(settings.learn_daily_minutes),
                id="settings-learn-daily-minutes",
                type="integer",
            )
            yield Static("", id="settings-error")
        yield Footer()

    def action_save(self) -> None:
        speed_raw = self.query_one("#settings-speed", Input).value
        try:
            target_speed_value = int(speed_raw)
        except ValueError:
            self._show_error("Target speed must be an integer.")
            return

        speed_unit_select = cast(
            "Select[TargetSpeedUnit]",
            self.query_one("#settings-speed-unit", Select),
        )
        target_speed_unit = speed_unit_select.value
        if isinstance(target_speed_unit, NoSelection):
            return
        target_speed_cpm = (
            cpm_from_wpm(target_speed_value)
            if target_speed_unit == TargetSpeedUnit.WPM
            else target_speed_value
        )

        alphabet_size_raw = self.query_one("#settings-alphabet-size", Input).value
        try:
            alphabet_size = int(alphabet_size_raw)
        except ValueError:
            self._show_error("Number of letters must be an integer.")
            return

        learn_daily_minutes_raw = self.query_one("#settings-learn-daily-minutes", Input).value
        try:
            learn_daily_minutes = int(learn_daily_minutes_raw)
        except ValueError:
            self._show_error("Daily learn minutes must be an integer.")
            return

        layout_select = cast("Select[str]", self.query_one("#settings-layout", Select))
        layout = layout_select.value
        if isinstance(layout, NoSelection):
            # Unreachable with allow_blank=False + an initial value, but keeps typing sound.
            return

        try:
            self._update_settings(
                layout=layout,
                target_speed_cpm=target_speed_cpm,
                target_speed_unit=target_speed_unit,
                alphabet_size=alphabet_size,
                learn_daily_minutes=learn_daily_minutes,
            )
        except SettingsValidationError as exc:
            self._show_error(str(exc))
            return

        self.app.pop_screen()

    def action_back(self) -> None:
        self.app.pop_screen()

    def _show_error(self, message: str) -> None:
        self.query_one("#settings-error", Static).update(f"[bold red]{message}[/]")
