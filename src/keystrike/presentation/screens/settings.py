from typing import ClassVar, cast

from textual.app import ComposeResult
from textual.binding import BindingType
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Input, Label, Select, Static
from textual.widgets.select import NoSelection

from keystrike.application.settings_use_cases import SettingsValidationError, UpdateSettings
from keystrike.application.wordlist_use_cases import ImportWordList, WordListError
from keystrike.domain.enums import TargetSpeedUnit
from keystrike.domain.generator import cpm_from_wpm, wpm_from_cpm
from keystrike.domain.protocols import LayoutRepository, SettingsRepository, WordListStore
from keystrike.domain.wordlist import DEFAULT_WORDLIST_URL
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
    SettingsScreen Horizontal {
        height: auto;
    }
    SettingsScreen #settings-wordlist-import {
        margin-left: 1;
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
        import_wordlist: ImportWordList,
        wordlist_store: WordListStore,
    ) -> None:
        super().__init__()
        self._settings_repo = settings_repo
        self._layout_repo = layout_repo
        self._update_settings = update_settings
        self._import_wordlist = import_wordlist
        self._wordlist_store = wordlist_store

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
            yield Label("Daily learn goal (minutes; 0 = no goal)")
            yield Input(
                value=str(settings.learn_daily_minutes),
                id="settings-learn-daily-minutes",
                type="integer",
            )
            yield Label("Word list URL (optional; import to cache)")
            with Horizontal():
                yield Input(
                    value=settings.wordlist_url,
                    placeholder=DEFAULT_WORDLIST_URL,
                    id="settings-wordlist-url",
                )
                yield Button("Import", id="settings-wordlist-import", variant="primary")
            yield Static(
                self._wordlist_status(settings.wordlist_url),
                id="settings-wordlist-status",
            )
            yield Static("", id="settings-error")
        yield Footer()

    def on_mount(self) -> None:
        self._refresh_wordlist_status()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "settings-wordlist-import":
            self._do_import()

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

        wordlist_url = self.query_one("#settings-wordlist-url", Input).value

        try:
            self._update_settings(
                layout=layout,
                target_speed_cpm=target_speed_cpm,
                target_speed_unit=target_speed_unit,
                alphabet_size=alphabet_size,
                learn_daily_minutes=learn_daily_minutes,
                wordlist_url=wordlist_url,
            )
        except SettingsValidationError as exc:
            self._show_error(str(exc))
            return

        self.app.pop_screen()

    def action_back(self) -> None:
        self.app.pop_screen()

    def _do_import(self) -> None:
        url = self.query_one("#settings-wordlist-url", Input).value.strip()
        if not url:
            url = DEFAULT_WORDLIST_URL
        try:
            count = self._import_wordlist(url)
        except WordListError as exc:
            self._show_error(str(exc))
            return
        self.query_one("#settings-error", Static).update("")
        self._refresh_wordlist_status(f"Imported {count} words.")
        self.query_one("#settings-wordlist-url", Input).value = url

    def _wordlist_status(self, url: str) -> str:
        if not url.strip():
            return "[dim]No word list — Markov-generated words.[/]"
        count = self._wordlist_store.cached_word_count(url.strip())
        if count is None:
            return "[dim]URL saved but not cached — import or Markov fallback.[/]"
        return f"[dim]{count} words cached.[/]"

    def _refresh_wordlist_status(self, message: str | None = None) -> None:
        url = self.query_one("#settings-wordlist-url", Input).value
        text = message or self._wordlist_status(url)
        self.query_one("#settings-wordlist-status", Static).update(text)

    def _show_error(self, message: str) -> None:
        self.query_one("#settings-error", Static).update(f"[bold red]{message}[/]")
