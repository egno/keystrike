from typing import ClassVar, cast

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Footer, Input, Label, Select, Static
from textual.widgets.select import NoSelection

from keystrike.application.settings_use_cases import SettingsValidationError, UpdateSettings
from keystrike.domain.protocols import LayoutRepository, SettingsRepository

_THEMES = ("dark", "light")


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
        Binding("ctrl+s", "save", "Save", priority=True),
        Binding("escape", "cancel", "Cancel", priority=True),
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
            yield Static("[bold]Settings[/]  [dim](Ctrl+S save, Esc cancel)[/]")
            yield Label("Layout")
            yield Select(layouts, value=settings.layout, id="settings-layout", allow_blank=False)
            yield Label("Target speed (chars/min)")
            yield Input(
                value=str(settings.target_speed_cpm),
                id="settings-speed",
                type="integer",
            )
            yield Label("Freeform text file (leave blank to disable)")
            yield Input(value=settings.freeform_path or "", id="settings-freeform-path")
            yield Label("Theme")
            yield Select(
                [(t, t) for t in _THEMES],
                value=settings.theme,
                id="settings-theme",
                allow_blank=False,
            )
            yield Static("", id="settings-error")
        yield Footer()

    def action_save(self) -> None:
        speed_raw = self.query_one("#settings-speed", Input).value
        try:
            target_speed_cpm = int(speed_raw)
        except ValueError:
            self._show_error("Target speed must be an integer.")
            return

        freeform_raw = self.query_one("#settings-freeform-path", Input).value.strip()
        layout_select = cast("Select[str]", self.query_one("#settings-layout", Select))
        theme_select = cast("Select[str]", self.query_one("#settings-theme", Select))
        layout = layout_select.value
        theme = theme_select.value
        if isinstance(layout, NoSelection) or isinstance(theme, NoSelection):
            # Unreachable with allow_blank=False + an initial value, but keeps typing sound.
            return

        try:
            self._update_settings(
                layout=layout,
                target_speed_cpm=target_speed_cpm,
                freeform_path=freeform_raw or None,
                theme=theme,
            )
        except SettingsValidationError as exc:
            self._show_error(str(exc))
            return

        self.app.pop_screen()

    def action_cancel(self) -> None:
        self.app.pop_screen()

    def _show_error(self, message: str) -> None:
        self.query_one("#settings-error", Static).update(f"[bold red]{message}[/]")
