from typing import ClassVar, cast

from rich.markup import escape
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Footer, Input, Label, Select, Static
from textual.widgets.select import NoSelection

from keystrike.application.ai_settings_use_cases import (
    AiSettingsValidationError,
    validate_ai_settings,
)
from keystrike.application.settings_use_cases import SettingsUpdate, SettingsValidationError
from keystrike.application.wordlist_use_cases import DEFAULT_WORDLIST_URL, WordListError
from keystrike.domain.ai_models import (
    AI_PROVIDER_OFF,
    AI_PROVIDER_OLLAMA,
    AI_PROVIDER_OPENAI,
    DEFAULT_AI_ENDPOINTS,
    AiSettings,
)
from keystrike.domain.enums import TargetSpeedUnit
from keystrike.domain.generator import cpm_from_wpm, wpm_from_cpm
from keystrike.presentation.bindings import BACK_BINDINGS, SAVE
from keystrike.presentation.services import SettingsServices


class FormError(ValueError):
    """A form field couldn't be parsed -- distinct from
    `SettingsValidationError`, which is the application layer rejecting an
    otherwise well-formed value. `action_save` catches both the same way,
    but keeping them separate means a form error can't be mistaken for
    (or silently absorbed into) a settings-domain rejection."""


class SettingsScreen(Screen[None]):
    DEFAULT_CSS = """
    SettingsScreen > Vertical {
        padding: 1 2;
        width: 60;
    }
    SettingsScreen Label,
    SettingsScreen #settings-wordlist-label,
    SettingsScreen #settings-ai-label {
        margin-top: 1;
    }
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        SAVE,
        Binding("ctrl+i", "import_wordlist", "Import", priority=True),
        Binding("ctrl+x", "clear_wordlist", "Clear", priority=True),
        Binding("ctrl+t", "test_ai", "Test AI", priority=True),
        *BACK_BINDINGS,
    ]

    def __init__(self, *, services: SettingsServices) -> None:
        super().__init__()
        self._services = services
        self._speed_unit = TargetSpeedUnit.WPM  # unit the speed input shows; set in compose

    def compose(self) -> ComposeResult:
        settings = self._services.settings_repo.load()
        layouts = self._layout_select_options()
        self._speed_unit = settings.target_speed_unit
        with Vertical():
            yield Static("[bold]Settings[/]  [dim](Ctrl+S save, Esc/q back)[/]")
            yield Label("Layout")
            yield Select(layouts, value=settings.layout, id="settings-layout", allow_blank=False)
            yield Label("Target speed")
            yield Input(
                value=str(settings.target_speed),
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
            yield from self._compose_ai_section()
            yield Static("", id="settings-error")
        yield Footer()

    def _compose_ai_section(self) -> ComposeResult:
        repo = self._services.ai_settings_repo
        if repo is None or self._services.update_ai_settings is None:
            return
        ai = repo.load()
        yield Static(
            "AI coach  [dim](Ctrl+T test · local to this device, never synced)[/]",
            id="settings-ai-label",
        )
        yield Select(
            [
                ("Off", AI_PROVIDER_OFF),
                ("Ollama", AI_PROVIDER_OLLAMA),
                ("OpenAI-compatible", AI_PROVIDER_OPENAI),
            ],
            value=ai.provider,
            id="settings-ai-provider",
            allow_blank=False,
        )
        yield Input(value=ai.model, placeholder="model", id="settings-ai-model")
        yield Input(value=ai.endpoint, placeholder="http://…", id="settings-ai-endpoint")
        yield Static(self._ai_hint(ai.provider), id="settings-ai-status")

    @property
    def _has_ai_section(self) -> bool:
        return (
            self._services.ai_settings_repo is not None
            and self._services.update_ai_settings is not None
        )

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action == "test_ai":
            return self._has_ai_section and self._services.check_ai_connection is not None
        return True

    @staticmethod
    def _ai_hint(provider: str) -> str:
        if provider == AI_PROVIDER_OPENAI:
            return "[dim]API key, if needed: set KEYSTRIKE_AI_API_KEY.[/]"
        if provider == AI_PROVIDER_OLLAMA:
            return "[dim]Sends key statistics to this server after each session.[/]"
        return "[dim]Off: nothing leaves this device.[/]"

    def _on_ai_provider_changed(self, provider: str) -> None:
        """A new provider gets its default endpoint, unless the user typed a
        custom one."""
        endpoint = self.query_one("#settings-ai-endpoint", Input)
        if not endpoint.value.strip() or endpoint.value in DEFAULT_AI_ENDPOINTS.values():
            endpoint.value = DEFAULT_AI_ENDPOINTS.get(provider, endpoint.value)
        self.query_one("#settings-ai-status", Static).update(self._ai_hint(provider))

    def _collect_ai_values(self) -> AiSettings | None:
        if not self._has_ai_section:
            return None
        provider = cast("Select[str]", self.query_one("#settings-ai-provider", Select)).value
        return AiSettings(
            provider=provider if isinstance(provider, str) else AI_PROVIDER_OFF,
            model=self.query_one("#settings-ai-model", Input).value,
            endpoint=self.query_one("#settings-ai-endpoint", Input).value,
        )

    def action_test_ai(self) -> None:
        check = self._services.check_ai_connection
        proposed = self._collect_ai_values()
        if check is None or proposed is None:
            return
        status = self.query_one("#settings-ai-status", Static)
        status.update("[dim]Testing…[/]")

        async def run() -> None:
            try:
                message = await check(proposed)
            except Exception as exc:
                status.update(f"[bold red]Failed: {escape(f'{type(exc).__name__}: {exc}')}[/]")
                return
            status.update(f"[green]{escape(message)}[/]")

        self.run_worker(run(), group="ai-test", exclusive=True, exit_on_error=False)

    def on_mount(self) -> None:
        self._refresh_layout_select()
        self._refresh_wordlist_status()

    def on_select_changed(self, event: Select.Changed) -> None:
        """Switching the unit converts the shown goal, so it keeps its meaning."""
        if event.select.id == "settings-ai-provider" and isinstance(event.value, str):
            self._on_ai_provider_changed(event.value)
            return
        if event.select.id != "settings-speed-unit" or isinstance(event.value, NoSelection):
            return
        unit = cast("TargetSpeedUnit", event.value)
        if unit == self._speed_unit:
            return
        self._speed_unit = unit
        speed_input = self.query_one("#settings-speed", Input)
        try:
            value = int(speed_input.value)
        except ValueError:
            return
        rate = self._services.get_keystrokes_per_word(self._services.settings_repo.load())
        converted = (
            cpm_from_wpm(value, rate) if unit == TargetSpeedUnit.CPM else wpm_from_cpm(value, rate)
        )
        speed_input.value = str(max(1, converted))

    def on_screen_resume(self) -> None:
        settings = self._services.settings_repo.load()
        self.query_one("#settings-alphabet-size", Input).value = str(settings.alphabet_size)
        self._refresh_layout_select()

    def action_import_wordlist(self) -> None:
        self._do_import()

    def action_clear_wordlist(self) -> None:
        self._do_clear()

    def _collect_form_values(self) -> SettingsUpdate:
        """Parse the form into a `SettingsUpdate`, or raise `FormError` --
        `action_save` owns the one place that turns that into a shown
        error, so parsing itself has no side effect."""
        target_speed_value = self._required_int(
            "#settings-speed", "Target speed must be an integer."
        )

        speed_unit_select = cast(
            "Select[TargetSpeedUnit]",
            self.query_one("#settings-speed-unit", Select),
        )
        target_speed_unit = speed_unit_select.value
        if isinstance(target_speed_unit, NoSelection):
            raise FormError("Target speed unit is required.")

        alphabet_size = self._required_int(
            "#settings-alphabet-size", "Number of letters must be an integer."
        )

        learn_daily_minutes = self._required_int(
            "#settings-learn-daily-minutes", "Daily learn minutes must be an integer."
        )

        layout_select = cast("Select[str]", self.query_one("#settings-layout", Select))
        layout = layout_select.value
        if isinstance(layout, NoSelection):
            # Unreachable with allow_blank=False + an initial value, but keeps typing sound.
            raise FormError("Layout is required.")

        return SettingsUpdate(
            layout=layout,
            target_speed=target_speed_value,
            target_speed_unit=target_speed_unit,
            alphabet_size=alphabet_size,
            learn_daily_minutes=learn_daily_minutes,
        )

    def action_save(self) -> None:
        try:
            values = self._collect_form_values()
            ai_values = self._collect_ai_values()
            if ai_values is not None:
                validate_ai_settings(ai_values)  # reject before saving anything
            self._services.update_settings(values)
            if ai_values is not None and self._services.update_ai_settings is not None:
                self._services.update_ai_settings(ai_values)
        except (FormError, SettingsValidationError, AiSettingsValidationError) as exc:
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

    def _required_int(self, widget_id: str, error: str) -> int:
        value = self._parse_int_field(self.query_one(widget_id, Input).value)
        if value is None:
            raise FormError(error)
        return value

    @staticmethod
    def _parse_int_field(raw: str) -> int | None:
        try:
            return int(raw)
        except ValueError:
            return None
