from typing import ClassVar, cast

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Footer, Input, Label, Select, Static
from textual.widgets.select import NoSelection

from keystrike.application.settings_use_cases import SettingsUpdate, SettingsValidationError
from keystrike.application.wordlist_use_cases import DEFAULT_WORDLIST_URL, WordListError
from keystrike.domain.enums import TargetSpeedUnit
from keystrike.domain.generator import cpm_from_wpm, wpm_from_cpm
from keystrike.presentation.bindings import BACK_BINDINGS, SAVE
from keystrike.presentation.services import SettingsServices


class SettingsScreen(Screen[None]):
    DEFAULT_CSS = """
    SettingsScreen > Vertical {
        padding: 1 2;
        width: 60;
    }
    SettingsScreen Label,
    SettingsScreen #settings-wordlist-label {
        margin-top: 1;
    }
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        SAVE,
        Binding("ctrl+i", "import_wordlist", "Import", priority=True),
        Binding("ctrl+x", "clear_wordlist", "Clear", priority=True),
        *BACK_BINDINGS,
    ]

    def __init__(self, *, services: SettingsServices) -> None:
        super().__init__()
        self._services = services

    def compose(self) -> ComposeResult:
        settings = self._services.settings_repo.load()
        layouts = self._layout_select_options()
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
            yield Label("Daily learn goal (minutes; 0 = no goal)")
            yield Input(
                value=str(settings.learn_daily_minutes),
                id="settings-learn-daily-minutes",
                type="integer",
            )
            yield Static(
                "Word list  [dim](Ctrl+I import, Ctrl+X clear)[/]",
                id="settings-wordlist-label",
            )
            yield Input(
                value=self._display_wordlist_url(settings.wordlist_url),
                id="settings-wordlist-url",
            )
            yield Static(
                self._wordlist_status(settings.wordlist_url),
                id="settings-wordlist-status",
            )
            yield Static("", id="settings-error")
        yield Footer()

    def on_mount(self) -> None:
        self._refresh_layout_select()
        self._refresh_wordlist_status()

    def on_screen_resume(self) -> None:
        settings = self._services.settings_repo.load()
        self.query_one("#settings-alphabet-size", Input).value = str(settings.alphabet_size)
        self._refresh_layout_select()

    def action_import_wordlist(self) -> None:
        self._do_import()

    def action_clear_wordlist(self) -> None:
        self._do_clear()

    def _collect_form_values(self) -> SettingsUpdate | None:
        target_speed_value = self._required_int(
            "#settings-speed", "Target speed must be an integer."
        )
        if target_speed_value is None:
            return None

        speed_unit_select = cast(
            "Select[TargetSpeedUnit]",
            self.query_one("#settings-speed-unit", Select),
        )
        target_speed_unit = speed_unit_select.value
        if isinstance(target_speed_unit, NoSelection):
            return None
        target_speed_cpm = (
            cpm_from_wpm(target_speed_value)
            if target_speed_unit == TargetSpeedUnit.WPM
            else target_speed_value
        )

        alphabet_size = self._required_int(
            "#settings-alphabet-size", "Number of letters must be an integer."
        )
        if alphabet_size is None:
            return None

        learn_daily_minutes = self._required_int(
            "#settings-learn-daily-minutes", "Daily learn minutes must be an integer."
        )
        if learn_daily_minutes is None:
            return None

        layout_select = cast("Select[str]", self.query_one("#settings-layout", Select))
        layout = layout_select.value
        if isinstance(layout, NoSelection):
            # Unreachable with allow_blank=False + an initial value, but keeps typing sound.
            return None

        return SettingsUpdate(
            layout=layout,
            target_speed_cpm=target_speed_cpm,
            target_speed_unit=target_speed_unit,
            alphabet_size=alphabet_size,
            learn_daily_minutes=learn_daily_minutes,
        )

    def action_save(self) -> None:
        values = self._collect_form_values()
        if values is None:
            return

        try:
            self._services.update_settings(values)
        except SettingsValidationError as exc:
            self._show_error(str(exc))
            return

        self.app.pop_screen()

    def action_back(self) -> None:
        self.app.pop_screen()

    @staticmethod
    def _display_wordlist_url(persisted_url: str) -> str:
        return persisted_url or DEFAULT_WORDLIST_URL

    def _do_clear(self) -> None:
        self._services.clear_wordlist()
        self.query_one("#settings-error", Static).update("")
        self.query_one("#settings-wordlist-url", Input).value = DEFAULT_WORDLIST_URL
        self._refresh_wordlist_status()

    def _do_import(self) -> None:
        url = self.query_one("#settings-wordlist-url", Input).value
        try:
            count = self._services.import_wordlist(url)
        except WordListError as exc:
            self._show_error(str(exc))
            return
        self.query_one("#settings-error", Static).update("")
        self._refresh_wordlist_status(f"Imported {count} words.")
        persisted = self._services.settings_repo.load().wordlist_url
        self.query_one("#settings-wordlist-url", Input).value = self._display_wordlist_url(
            persisted,
        )

    def _wordlist_status(self, persisted_url: str) -> str:
        persisted = persisted_url.strip()
        if not persisted:
            return "[dim]Markov words.[/]"
        count = self._services.get_wordlist_cache_status(persisted)
        if count is not None:
            return f"[dim]{count} words cached.[/]"
        return "[dim]Not cached.[/]"

    def _refresh_wordlist_status(self, message: str | None = None) -> None:
        persisted = self._services.settings_repo.load().wordlist_url
        text = message or self._wordlist_status(persisted)
        self.query_one("#settings-wordlist-status", Static).update(text)

    def _layout_select_options(self) -> list[tuple[str, str]]:
        return [(name, name) for name in self._services.layout_repo.list_available()]

    def _refresh_layout_select(self) -> None:
        layout_select = cast("Select[str]", self.query_one("#settings-layout", Select))
        current = layout_select.value
        layout_select.set_options(self._layout_select_options())
        if not isinstance(current, NoSelection):
            layout_select.value = current

    def _show_error(self, message: str) -> None:
        self.query_one("#settings-error", Static).update(f"[bold red]{message}[/]")

    def _required_int(self, widget_id: str, error: str) -> int | None:
        value = self._parse_int_field(self.query_one(widget_id, Input).value)
        if value is None:
            self._show_error(error)
        return value

    @staticmethod
    def _parse_int_field(raw: str) -> int | None:
        try:
            return int(raw)
        except ValueError:
            return None
