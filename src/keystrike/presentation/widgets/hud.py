from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Static

from keystrike.domain.daily_learn import DailyLearnBudget
from keystrike.domain.protocols import Clock, DailyLearnBudgetProvider
from keystrike.domain.session import Session


def _format_goal_segment(session: Session, sessions_to_goal: int | None) -> str:
    if session.focus_key is None:
        return ""
    focus_char = chr(session.focus_key)
    goal_text = f"~{sessions_to_goal} sessions" if sessions_to_goal is not None else "learning…"
    return f"   Goal[{focus_char}]: [bold]{goal_text}[/]"


def _format_daily_learn_segment(budget: DailyLearnBudget | None) -> str:
    if budget is None or not budget.limited:
        return ""
    used_min = budget.used_ns / 1e9 / 60
    limit_min = budget.limit_ns / 1e9 / 60
    return f"   Learn: [bold]{used_min:.1f}[/]/{limit_min:g} min"


def _format_hud(
    session: Session,
    elapsed_ns: int,
    sessions_to_goal: int | None,
    daily_budget: DailyLearnBudget | None = None,
) -> str:
    minutes = elapsed_ns / 1e9 / 60.0
    wpm = (session.correct_count / 5.0) / minutes if minutes > 0 else 0.0
    accuracy = (session.correct_count / session.total_count) if session.total_count else 1.0
    elapsed_s = elapsed_ns / 1e9
    return (
        f"WPM: [bold]{wpm:5.1f}[/]   "
        f"Acc: [bold]{accuracy * 100:5.1f}%[/]   "
        f"Time: [bold]{elapsed_s:5.1f}s[/]   "
        f"Keys: [bold]{session.total_count}[/]"
        f"{_format_goal_segment(session, sessions_to_goal)}"
        f"{_format_daily_learn_segment(daily_budget)}"
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
        sessions_to_goal: int | None = None,
        *,
        get_daily_learn_budget: DailyLearnBudgetProvider | None = None,
    ) -> None:
        super().__init__()
        self._session = session
        self._clock = clock
        self._sessions_to_goal = sessions_to_goal
        self._get_daily_learn_budget = get_daily_learn_budget

    def compose(self) -> ComposeResult:
        yield Static(_format_hud(self._session, 0, self._sessions_to_goal), id="hud-text")

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
        static.update(
            _format_hud(self._session, elapsed, self._sessions_to_goal, daily_budget),
        )
