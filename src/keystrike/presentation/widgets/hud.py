from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Static

from keystrike.domain.daily_learn import DailyLearnBudget
from keystrike.domain.null_adapters import NULL_DAILY_LEARN_BUDGET
from keystrike.domain.protocols import Clock, DailyLearnBudgetProvider
from keystrike.domain.session import Session


def _format_daily_learn_segment(budget: DailyLearnBudget) -> str:
    if not budget.limited:
        return ""
    remaining_min = budget.remaining_ns / 1e9 / 60
    limit_min = budget.limit_ns / 1e9 / 60
    return f"   Goal: [bold]{remaining_min:.1f}[/]/{limit_min:g} min"


def _format_sessions_goal_segment(focus_key: int | None, sessions_to_goal: int | None) -> str:
    if focus_key is None:
        return ""
    char = chr(focus_key)
    if sessions_to_goal is None:
        return f"   Goal[{char}]: learning…"
    if sessions_to_goal == 0:
        return f"   Goal[{char}]: done"
    return f"   Goal[{char}]: ~{sessions_to_goal} sessions"


def _format_focus_segment(focus_key: int | None, focus_reason: str | None) -> str:
    if focus_key is None or not focus_reason:
        return ""
    return f"   Focus: [bold]{chr(focus_key)}[/] [dim]{focus_reason}[/]"


def _format_hud(
    session: Session,
    daily_budget: DailyLearnBudget,
    *,
    focus_reason: str | None = None,
    sessions_to_goal: int | None = None,
) -> str:
    accuracy = (session.correct_count / session.total_count) if session.total_count else 1.0
    return (
        f"Acc: [bold]{accuracy * 100:5.1f}%[/]"
        f"{_format_daily_learn_segment(daily_budget)}"
        f"{_format_sessions_goal_segment(session.focus_key, sessions_to_goal)}"
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
        get_daily_learn_budget: DailyLearnBudgetProvider = NULL_DAILY_LEARN_BUDGET,
        focus_reason: str | None = None,
        sessions_to_goal: int | None = None,
    ) -> None:
        super().__init__()
        self._session = session
        self._clock = clock
        self._get_daily_learn_budget = get_daily_learn_budget
        self._focus_reason = focus_reason
        self._sessions_to_goal = sessions_to_goal

    def compose(self) -> ComposeResult:
        yield Static(
            _format_hud(
                self._session,
                self._get_daily_learn_budget(),
                focus_reason=self._focus_reason,
                sessions_to_goal=self._sessions_to_goal,
            ),
            id="hud-text",
        )

    def on_mount(self) -> None:
        self.set_interval(0.1, self.refresh_display)

    def refresh_display(self) -> None:
        started = self._session.typing_started_at_ns
        elapsed = (self._clock.now_ns() - started) if started is not None else 0
        daily_budget = self._get_daily_learn_budget(extra_ns=elapsed)
        static = self.query_one("#hud-text", Static)
        static.update(
            _format_hud(
                self._session,
                daily_budget,
                focus_reason=self._focus_reason,
                sessions_to_goal=self._sessions_to_goal,
            ),
        )

    def set_session(
        self,
        session: Session,
        *,
        focus_reason: str | None = None,
        sessions_to_goal: int | None = None,
    ) -> None:
        self._session = session
        self._focus_reason = focus_reason
        self._sessions_to_goal = sessions_to_goal
        self.refresh_display()
