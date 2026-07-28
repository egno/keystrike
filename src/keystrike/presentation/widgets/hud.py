from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Static

from keystrike.domain.daily_learn import DailyLearnBudget
from keystrike.domain.protocols import Clock, DailyLearnBudgetProvider
from keystrike.domain.session import Session


def _format_goal_segment(budget: DailyLearnBudget | None) -> str:
    if budget is None or not budget.limited:
        return ""
    remaining_min = budget.remaining_ns / 1e9 / 60
    limit_min = budget.limit_ns / 1e9 / 60
    return f"   Goal: [bold]{remaining_min:.1f}[/]/{limit_min:g} min"


def _format_focus_segment(focus_key: int | None, focus_reason: str | None) -> str:
    if focus_key is None or not focus_reason:
        return ""
    return f"   Focus: [bold]{chr(focus_key)}[/] [dim]{focus_reason}[/]"


def _format_hud(
    session: Session,
    elapsed_ns: int,
    daily_budget: DailyLearnBudget | None = None,
    *,
    focus_reason: str | None = None,
) -> str:
    minutes = elapsed_ns / 1e9 / 60.0
    wpm = (session.correct_count / 5.0) / minutes if minutes > 0 else 0.0
    accuracy = (session.correct_count / session.total_count) if session.total_count else 1.0
    return (
        f"WPM: [bold]{wpm:5.1f}[/]   "
        f"Acc: [bold]{accuracy * 100:5.1f}%[/]"
        f"{_format_goal_segment(daily_budget)}"
        f"{_format_focus_segment(session.focus_key, focus_reason)}"
    )


class HUD(Widget):
    DEFAULT_CSS = """
    HUD {
        padding: 0 2;
        height: 1;
        color: $accent;
    }
    """

    def __init__(
        self,
        session: Session,
        clock: Clock,
        *,
        get_daily_learn_budget: DailyLearnBudgetProvider | None = None,
        focus_reason: str | None = None,
    ) -> None:
        super().__init__()
        self._session = session
        self._clock = clock
        self._get_daily_learn_budget = get_daily_learn_budget
        self._focus_reason = focus_reason

    def compose(self) -> ComposeResult:
        yield Static(_format_hud(self._session, 0, focus_reason=self._focus_reason), id="hud-text")

    def on_mount(self) -> None:
        self.set_interval(0.1, self.refresh_display)

    def refresh_display(self) -> None:
        started = self._session.typing_started_at_ns
        elapsed = (self._clock.now_ns() - started) if started is not None else 0
        daily_budget = (
            self._get_daily_learn_budget(extra_ns=elapsed)
            if self._get_daily_learn_budget is not None
            else None
        )
        static = self.query_one("#hud-text", Static)
        static.update(_format_hud(self._session, elapsed, daily_budget, focus_reason=self._focus_reason))

    def set_session(self, session: Session, *, focus_reason: str | None = None) -> None:
        self._session = session
        self._focus_reason = focus_reason
        self.refresh_display()
