from typing import ClassVar

from textual import events
from textual.app import ComposeResult
from textual.binding import BindingType
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Footer, Static

from keystrike.application.session_use_cases import (
    AbortSession,
    FinishSession,
    RecordKeystroke,
    StartSession,
    format_session_stats_line,
)
from keystrike.domain.enums import Mode
from keystrike.domain.models import Layout, SessionResult
from keystrike.domain.null_adapters import (
    NULL_DAILY_LEARN_BUDGET,
    NULL_STATS_REBUILDER,
)
from keystrike.domain.protocols import Clock, DailyLearnBudgetProvider, StatsRebuilder
from keystrike.presentation.bindings import BACK_BINDINGS
from keystrike.presentation.session_prep import PrepareNextSession, SessionPrep
from keystrike.presentation.widgets.hud import HUD
from keystrike.presentation.widgets.kb_heatmap import KbHeatmap
from keystrike.presentation.widgets.typing_area import TypingArea


class PracticeScreen(Screen[None]):
    DEFAULT_CSS = """
    PracticeScreen > Vertical {
        padding: 1 2;
    }
    PracticeScreen #last-session-stats {
        color: $text-muted;
        padding: 0 2;
        height: 1;
    }
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        *BACK_BINDINGS,
    ]

    def __init__(
        self,
        *,
        start: StartSession,
        record: RecordKeystroke,
        finish: FinishSession,
        clock: Clock,
        initial: SessionPrep,
        prepare_next: PrepareNextSession,
        rebuild_aggregates: StatsRebuilder = NULL_STATS_REBUILDER,
        get_daily_learn_budget: DailyLearnBudgetProvider = NULL_DAILY_LEARN_BUDGET,
    ) -> None:
        super().__init__()
        self._start = start
        self._record = record
        self._finish = finish
        self._clock = clock
        self._prepare_next = prepare_next
        self._rebuild_aggregates = rebuild_aggregates
        self._get_daily_learn_budget = (
            get_daily_learn_budget
            if initial.mode is Mode.ADAPTIVE
            else NULL_DAILY_LEARN_BUDGET
        )
        self._layout_obj: Layout | None = initial.layout_obj
        self._lesson_heatmap = initial.lesson_heatmap
        self._lesson_urgency = initial.lesson_urgency
        self._focus_key = initial.focus_key
        self._focus_reason = initial.focus_reason
        self._kb_heatmap: KbHeatmap | None = None
        self._session = self._start(
            initial.target_text,
            layout=initial.layout,
            mode=initial.mode,
            focus_key=initial.focus_key,
        )
        self._typing_area = TypingArea(self._session)
        self._hud = HUD(
            self._session,
            clock,
            get_daily_learn_budget=(
                self._get_daily_learn_budget if initial.mode is Mode.ADAPTIVE else None
            ),
            focus_reason=initial.focus_reason,
        )

    def compose(self) -> ComposeResult:
        with Vertical():
            yield self._hud
            yield self._typing_area
            if self._layout_obj is not None and self._lesson_heatmap is not None:
                self._kb_heatmap = KbHeatmap(
                    self._layout_obj,
                    self._lesson_heatmap,
                    self._focus_key,
                    self._lesson_urgency,
                )
                yield self._kb_heatmap
            yield Static("", id="last-session-stats")
        yield Footer()

    def on_mount(self) -> None:
        self.focus()

    def on_key(self, event: events.Key) -> None:
        key = event.key
        char: str | None = event.character

        if key == "backspace":
            self._record.backspace(self._session)
        elif key == "space":
            self._record(self._session, " ")
        elif char is not None and len(char) == 1 and char.isprintable():
            self._record(self._session, char)
        else:
            return

        event.stop()
        self._typing_area.refresh_display()

        if self._session.mode is Mode.ADAPTIVE and self._daily_limit_reached():
            self._finish_session(start_next=False)
            return

        if self._session.finished:
            self._finish_session()

    def _current_elapsed_ns(self) -> int:
        started = self._session.typing_started_at_ns
        if started is None:
            return 0
        return self._clock.now_ns() - started

    def _daily_limit_reached(self) -> bool:
        return self._get_daily_learn_budget(extra_ns=self._current_elapsed_ns()).limit_reached

    def _finish_session(self, *, start_next: bool = True) -> None:
        result = self._finish(self._session)
        self._rebuild_aggregates(result.layout)
        self._show_last_session_stats(result)
        if not start_next:
            return
        prep = self._prepare_next()
        if prep is None:
            return
        self._begin_session(prep)

    def _show_last_session_stats(self, result: SessionResult) -> None:
        self.query_one("#last-session-stats", Static).update(format_session_stats_line(result))

    def _begin_session(self, prep: SessionPrep) -> None:
        self._layout_obj = prep.layout_obj
        self._lesson_heatmap = prep.lesson_heatmap
        self._lesson_urgency = prep.lesson_urgency
        self._focus_key = prep.focus_key
        self._focus_reason = prep.focus_reason
        self._session = self._start(
            prep.target_text,
            layout=prep.layout,
            mode=prep.mode,
            focus_key=prep.focus_key,
        )
        self._typing_area.set_session(self._session)
        self._hud.set_session(self._session, focus_reason=prep.focus_reason)
        if self._kb_heatmap is not None and prep.layout_obj and prep.lesson_heatmap is not None:
            self._kb_heatmap.refresh_heatmap(
                prep.layout_obj,
                prep.lesson_heatmap,
                prep.focus_key,
                prep.lesson_urgency,
            )

    def action_back(self) -> None:
        AbortSession()(self._session)
        self.app.pop_screen()
