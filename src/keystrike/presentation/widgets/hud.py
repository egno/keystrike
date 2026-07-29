from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Static

from keystrike.domain.daily_learn import DailyLearnBudget, format_daily_learn_display
from keystrike.domain.null_adapters import NULL_DAILY_LEARN_BUDGET
from keystrike.domain.protocols import Clock, DailyLearnBudgetProvider
from keystrike.domain.session import Session, active_typing_duration_ns, is_typing_idle


def learn_timer_dimmed(session: Session, now_ns: int) -> bool:
    if session.typing_started_at_ns is None or session.last_keystroke_at_ns is None:
        return True
    return is_typing_idle(session, now_ns)


def _format_daily_learn_segment(budget: DailyLearnBudget, *, dim: bool) -> str:
    segment = format_daily_learn_display(budget, label="   Learn:")
    if not segment:
        return ""
    colored = f"[green]{segment}[/]" if budget.limit_reached else segment
    return f"[dim]{colored}[/]" if dim else colored


def _format_focus_segment(focus_key: int | None, focus_reason: str | None) -> str:
    if focus_key is None or not focus_reason:
        return ""
    return f"   Focus: [bold]{chr(focus_key)}[/] [dim]{focus_reason}[/]"


def _format_hud(
    session: Session,
    daily_budget: DailyLearnBudget,
    *,
    focus_reason: str | None = None,
    dim_learn: bool = True,
) -> str:
    accuracy = (session.correct_count / session.total_count) if session.total_count else 1.0
    return (
        f"Acc: [bold]{accuracy * 100:5.1f}%[/]"
        f"{_format_daily_learn_segment(daily_budget, dim=dim_learn)}"
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
    ) -> None:
        super().__init__()
        self._session = session
        self._clock = clock
        self._get_daily_learn_budget = get_daily_learn_budget
        self._focus_reason = focus_reason

    def compose(self) -> ComposeResult:
        yield Static(
            _format_hud(
                self._session,
                self._get_daily_learn_budget(),
                focus_reason=self._focus_reason,
            ),
            id="hud-text",
        )

    def on_mount(self) -> None:
        self.set_interval(0.1, self.refresh_display)

    def refresh_display(self) -> None:
        now_ns = self._clock.now_ns()
        elapsed = active_typing_duration_ns(self._session, now_ns)
        daily_budget = self._get_daily_learn_budget(extra_ns=elapsed)
        static = self.query_one("#hud-text", Static)
        static.update(
            _format_hud(
                self._session,
                daily_budget,
                focus_reason=self._focus_reason,
                dim_learn=learn_timer_dimmed(self._session, now_ns),
            ),
        )

    def set_session(
        self,
        session: Session,
        *,
        focus_reason: str | None = None,
    ) -> None:
        self._session = session
        self._focus_reason = focus_reason
        self.refresh_display()
