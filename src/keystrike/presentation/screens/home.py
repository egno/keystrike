from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import VerticalScroll
from textual.message import Message
from textual.screen import Screen
from textual.widgets import Footer, Static

from keystrike.application.settings_use_cases import CycleLayout
from keystrike.domain.daily_learn import DailyLearnBudget
from keystrike.domain.null_adapters import NULL_DAILY_LEARN_BUDGET
from keystrike.domain.protocols import DailyLearnBudgetProvider, SettingsRepository


def _format_daily_learn_line(budget: DailyLearnBudget) -> str:
    if not budget.limited:
        return ""
    limit_min = budget.limit_ns / 1e9 / 60
    if budget.limit_reached:
        return f"[dim]Daily learn limit reached ({limit_min:g} min).[/]"
    used_min = budget.used_ns / 1e9 / 60
    remaining_min = budget.remaining_ns / 1e9 / 60
    return (
        f"Learn today: [bold]{used_min:.1f}[/]/{limit_min:g} min "
        f"([bold]{remaining_min:.1f}[/] left)"
    )


def _hero_text(layout: str, learn_budget: DailyLearnBudget) -> str:
    lines = [
        "[bold cyan]keystrike[/]  [dim]offline typing tutor[/]",
        f"Layout: [bold]{layout}[/]  [dim](l switch)[/]",
    ]
    daily = _format_daily_learn_line(learn_budget)
    if daily:
        lines.append(daily)
    return "\n".join(lines)


class HomeScreen(Screen[None]):
    DEFAULT_CSS = """
    HomeScreen {
        align: center top;
    }
    HomeScreen > VerticalScroll {
        height: 1fr;
        width: 100%;
    }
    HomeScreen #home-hero {
        width: 100%;
        height: auto;
        padding: 1 2;
        text-align: center;
    }
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("enter", "practice_adaptive", "Adaptive"),
        Binding("s", "open_stats", "Stats"),
        Binding("o", "open_settings", "Settings"),
        Binding("l", "cycle_layout", "Switch layout"),
    ]

    class StartPractice(Message):
        pass

    class OpenStats(Message):
        pass

    class OpenSettings(Message):
        pass

    def __init__(
        self,
        *,
        settings_repo: SettingsRepository,
        cycle_layout: CycleLayout,
        get_daily_learn_budget: DailyLearnBudgetProvider = NULL_DAILY_LEARN_BUDGET,
    ) -> None:
        super().__init__()
        self._settings_repo = settings_repo
        self._cycle_layout = cycle_layout
        self._get_daily_learn_budget = get_daily_learn_budget

    def compose(self) -> ComposeResult:
        yield VerticalScroll(Static(self._render_hero(), id="home-hero"))
        yield Footer()

    def on_screen_resume(self) -> None:
        self._refresh_hero()

    def _render_hero(self) -> str:
        settings = self._settings_repo.load()
        return _hero_text(settings.layout, self._get_daily_learn_budget())

    def _refresh_hero(self) -> None:
        self.query_one("#home-hero", Static).update(self._render_hero())

    def action_practice_adaptive(self) -> None:
        self.post_message(self.StartPractice())

    def action_open_stats(self) -> None:
        self.post_message(self.OpenStats())

    def action_open_settings(self) -> None:
        self.post_message(self.OpenSettings())

    def action_cycle_layout(self) -> None:
        self._cycle_layout()
        self._refresh_hero()
