from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Static

from keystrike.domain.daily_learn import DailyLearnBudget, daily_learn_display
from keystrike.domain.focus import FocusReason
from keystrike.domain.null_adapters import NULL_DAILY_LEARN_BUDGET
from keystrike.domain.protocols import DailyLearnBudgetProvider
from keystrike.domain.session import Session, session_accuracy
from keystrike.presentation.formatting.daily_learn import format_daily_learn_minutes
from keystrike.presentation.widgets.kb_heatmap import (
    focus_reason_label_short,
    focus_transition_pair,
)


def _format_daily_learn_segment(budget: DailyLearnBudget) -> str:
    display = daily_learn_display(budget)
    if not display.shown:
        return ""
    segment = f"   Learn: {format_daily_learn_minutes(display)}"
    return f"[green]{segment}[/]" if display.limit_reached else segment


def _format_focus_segment(focus_key: int | None, focus_reason: FocusReason | None) -> str:
    if focus_key is None or focus_reason is None:
        return ""
    transition = focus_transition_pair(focus_reason)
    label = transition.chars() if transition is not None else chr(focus_key)
    reason = focus_reason_label_short(focus_reason)
    return f"   Focus: [bold]{label}[/] · [dim]{reason}[/]"


def _format_hud(
    session: Session,
    daily_budget: DailyLearnBudget,
    *,
    focus_reason: FocusReason | None = None,
) -> str:
    accuracy = session_accuracy(session)
    return (
        f"Acc: [bold]{accuracy * 100:5.1f}%[/]"
        f"{_format_daily_learn_segment(daily_budget)}"
        f"{_format_focus_segment(session.focus_key, focus_reason)}"
    )


class HUD(Widget):
    """Shows the current lesson's accuracy, daily learn time, and focus key
    as a fixed snapshot taken when the lesson starts -- it does not tick
    while typing; call `set_session` to refresh it for the next lesson."""

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
        *,
        get_daily_learn_budget: DailyLearnBudgetProvider = NULL_DAILY_LEARN_BUDGET,
        focus_reason: FocusReason | None = None,
    ) -> None:
        super().__init__()
        self._session = session
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

    def refresh_display(self) -> None:
        static = self.query_one("#hud-text", Static)
        static.update(
            _format_hud(
                self._session,
                self._get_daily_learn_budget(),
                focus_reason=self._focus_reason,
            ),
        )

    def set_session(
        self,
        session: Session,
        *,
        focus_reason: FocusReason | None = None,
    ) -> None:
        self._session = session
        self._focus_reason = focus_reason
        self.refresh_display()
