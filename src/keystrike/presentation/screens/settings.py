from collections.abc import Mapping
from typing import ClassVar, cast

from rich.markup import escape
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Footer, Input, Label, Select, Static
from textual.widgets.select import NoSelection

from keystrike.application.advisor_use_cases import (
    AdvisorConfigError,
    OffDeviceConfirmationRequired,
)
from keystrike.application.settings_use_cases import SettingsUpdate, SettingsValidationError
from keystrike.application.wordlist_use_cases import DEFAULT_WORDLIST_URL, WordListError
from keystrike.domain.advice import NULL_ADVISOR_NAME, AdvisorSpec, SettingField
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
    SettingsScreen #settings-advisor-label {
        margin-top: 1;
    }
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        SAVE,
        Binding("ctrl+i", "import_wordlist", "Import", priority=True),
        Binding("ctrl+x", "clear_wordlist", "Clear", priority=True),
        Binding("ctrl+t", "test_advisor", "Test advisor", priority=True),
        *BACK_BINDINGS,
    ]

    def __init__(self, *, services: SettingsServices) -> None:
        super().__init__()
        self._services = services
        self._speed_unit = TargetSpeedUnit.WPM  # unit the speed input shows; set in compose
        # Advisor whose off-device notice was shown; the next save confirms it.
        self._confirm_pending: str | None = None

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
            yield from self._compose_advisor_section()
            yield Static("", id="settings-error")
        yield Footer()

    # -- advisor section ------------------------------------------------------

    @property
    def _has_advisor_section(self) -> bool:
        return (
            self._services.advisor_registry is not None
            and self._services.advisor_config_repo is not None
            and self._services.update_advisor_config is not None
        )

    def _compose_advisor_section(self) -> ComposeResult:
        registry = self._services.advisor_registry
        repo = self._services.advisor_config_repo
        if not self._has_advisor_section or registry is None or repo is None:
            return
        config = repo.load()
        spec = registry.get(config.active)
        yield Static(
            "Advisor  [dim](Ctrl+T test · local to this device, never synced)[/]",
            id="settings-advisor-label",
        )
        yield Select(
            [(s.label, s.name) for s in registry.specs()],
            value=spec.name,
            id="settings-advisor",
            allow_blank=False,
        )
        with Vertical(id="settings-advisor-form"):
            yield from self._advisor_widgets(spec, config.section(spec.name))
        yield Static(self._advisor_hint(spec), id="settings-advisor-status")
        for error in self._services.plugin_errors:
            yield Static(f"[yellow]{escape(error)}[/]", classes="settings-plugin-error")

    @staticmethod
    def _field_id(name: str) -> str:
        return f"settings-advisor-field-{name}"

    def _advisor_widgets(
        self, spec: AdvisorSpec, values: Mapping[str, str]
    ) -> list[Label | Input | Select[str]]:
        widgets: list[Label | Input | Select[str]] = []
        for field in spec.settings:
            value = values.get(field.name, field.default)
            widgets.append(Label(field.label))
            widgets.append(self._field_widget(field, value))
        return widgets

    def _field_widget(self, field: SettingField, value: str) -> Input | Select[str]:
        if field.choices:
            chosen = value if value in field.choices else field.choices[0]
            return Select(
                [(c, c) for c in field.choices],
                value=chosen,
                id=self._field_id(field.name),
                allow_blank=False,
            )
        return Input(value=value, id=self._field_id(field.name))

    @staticmethod
    def _advisor_hint(spec: AdvisorSpec) -> str:
        hints = [f"{f.env_hint}" for f in spec.settings if f.env_hint]
        if spec.capabilities.sends_data_off_device:
            text = "Sends key statistics to the configured server after each session."
            if hints:
                text += f" Secrets: set {', '.join(hints)}."
            return f"[dim]{escape(text)}[/]"
        if spec.name == NULL_ADVISOR_NAME:
            return "[dim]Off: no advice, nothing leaves this device.[/]"
        return "[dim]Runs on this device: nothing leaves it.[/]"

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action == "test_advisor":
            return self._has_advisor_section and self._services.test_advisor is not None
        return True

    def _selected_advisor(self) -> str:
        select = cast("Select[str]", self.query_one("#settings-advisor", Select))
        value = select.value
        return value if isinstance(value, str) else NULL_ADVISOR_NAME

    def _collect_advisor_values(self) -> tuple[str, dict[str, str]] | None:
        registry = self._services.advisor_registry
        if not self._has_advisor_section or registry is None:
            return None
        active = self._selected_advisor()
        values: dict[str, str] = {}
        for field in registry.get(active).settings:
            widget = self.query_one(f"#{self._field_id(field.name)}")
            raw = cast("Input | Select[str]", widget).value
            values[field.name] = raw if isinstance(raw, str) else field.default
        return active, values

    async def _on_advisor_changed(self, name: str) -> None:
        """Draw the new advisor's form from its `SettingField`s."""
        registry = self._services.advisor_registry
        repo = self._services.advisor_config_repo
        if registry is None or repo is None:
            return
        self._confirm_pending = None
        spec = registry.get(name)
        form = self.query_one("#settings-advisor-form", Vertical)
        await form.remove_children()
        await form.mount_all(self._advisor_widgets(spec, repo.load().section(spec.name)))
        self.query_one("#settings-advisor-status", Static).update(self._advisor_hint(spec))

    def action_test_advisor(self) -> None:
        test = self._services.test_advisor
        proposed = self._collect_advisor_values()
        if test is None or proposed is None:
            return
        active, values = proposed
        status = self.query_one("#settings-advisor-status", Static)
        status.update("[dim]Testing…[/]")

        async def run() -> None:
            try:
                message = await test(active, values)
            except Exception as exc:
                status.update(f"[bold red]Failed: {escape(f'{type(exc).__name__}: {exc}')}[/]")
                return
            status.update(f"[green]{escape(message)}[/]")

        self.run_worker(run(), group="advisor-test", exclusive=True, exit_on_error=False)

    def on_mount(self) -> None:
        self._refresh_layout_select()
        self._refresh_wordlist_status()

    async def on_select_changed(self, event: Select.Changed) -> None:
        """Switching the unit converts the shown goal, so it keeps its meaning."""
        if event.select.id == "settings-advisor" and isinstance(event.value, str):
            await self._on_advisor_changed(event.value)
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
        advisor: tuple[str, dict[str, str]] | None = None
        try:
            values = self._collect_form_values()
            advisor = self._collect_advisor_values()
            update_advisor = self._services.update_advisor_config
            confirm = advisor is not None and self._confirm_pending == advisor[0]
            if advisor is not None and update_advisor is not None:
                # reject before saving anything
                update_advisor.check(*advisor, confirm_off_device=confirm)
            self._services.update_settings(values)
            if advisor is not None and update_advisor is not None:
                update_advisor(*advisor, confirm_off_device=confirm)
        except OffDeviceConfirmationRequired as exc:
            assert advisor is not None
            self._confirm_pending = advisor[0]
            self.query_one("#settings-error", Static).update(f"[yellow]{escape(str(exc))}[/]")
            return
        except (FormError, SettingsValidationError, AdvisorConfigError) as exc:
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
