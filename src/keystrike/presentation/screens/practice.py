from typing import ClassVar

from textual import events
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Footer

from keystrike.application.session_use_cases import (
    AbortSession,
    FinishSession,
    RecordKeystroke,
    StartSession,
)
from keystrike.domain.enums import Mode
from keystrike.domain.models import Layout
from keystrike.domain.null_adapters import (
    NULL_DAILY_LEARN_BUDGET,
    NULL_LEARNING_RATE_ESTIMATOR,
    NULL_STATS_REBUILDER,
)
from keystrike.domain.protocols import (
    Clock,
    DailyLearnBudgetProvider,
    LearningRateEstimator,
    StatsRebuilder,
)
from keystrike.presentation.screens.results import ResultsScreen
from keystrike.presentation.widgets.hud import HUD
from keystrike.presentation.widgets.kb_heatmap import KbHeatmap
from keystrike.presentation.widgets.typing_area import TypingArea


class PracticeScreen(Screen[None]):
    DEFAULT_CSS = """
    PracticeScreen > Vertical {
        padding: 1 2;
    }
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("ctrl+q", "quit_app", "Quit", priority=True),
        Binding("escape", "abort", "Abort", priority=True),
    ]

    def __init__(
        self,
        *,
        start: StartSession,
        record: RecordKeystroke,
        finish: FinishSession,
        clock: Clock,
        target_text: str,
        layout: str = "qwerty",
        mode: Mode = Mode.FREE,
        focus_key: int | None = None,
        rebuild_aggregates: StatsRebuilder = NULL_STATS_REBUILDER,
        get_learning_rate: LearningRateEstimator = NULL_LEARNING_RATE_ESTIMATOR,
        get_daily_learn_budget: DailyLearnBudgetProvider = NULL_DAILY_LEARN_BUDGET,
        layout_obj: Layout | None = None,
        lesson_heatmap: dict[int, float] | None = None,
    ) -> None:
        super().__init__()
        self._start = start
        self._record = record
        self._finish = finish
        self._clock = clock
        self._rebuild_aggregates = rebuild_aggregates
        self._layout_obj = layout_obj
        self._lesson_heatmap = lesson_heatmap
        self._focus_key = focus_key
        self._get_daily_learn_budget = (
            get_daily_learn_budget if mode is Mode.ADAPTIVE else NULL_DAILY_LEARN_BUDGET
        )
        self._session = self._start(target_text, layout=layout, mode=mode, focus_key=focus_key)
        sessions_to_goal = (
            get_learning_rate(layout, focus_key) if focus_key is not None else None
        )
        self._typing_area = TypingArea(self._session)
        self._hud = HUD(
            self._session,
            clock,
            sessions_to_goal,
            get_daily_learn_budget=(
                self._get_daily_learn_budget if mode is Mode.ADAPTIVE else None
            ),
        )

    def compose(self) -> ComposeResult:
        with Vertical():
            yield self._hud
            yield self._typing_area
            if self._layout_obj is not None and self._lesson_heatmap is not None:
                yield KbHeatmap(self._layout_obj, self._lesson_heatmap, self._focus_key)
        yield Footer()

    def on_mount(self) -> None:
        self.focus()

    def on_key(self, event: events.Key) -> None:
        # Textual's Key event: event.character is the printable char (or None),
        # event.key is the symbolic name ("backspace", "enter", "space", etc.).
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
            self._finish_session()
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

    def _finish_session(self) -> None:
        result = self._finish(self._session)
        self._rebuild_aggregates(result.layout)
        self.app.switch_screen(ResultsScreen(result))

    def action_quit_app(self) -> None:
        self.app.exit()

    def action_abort(self) -> None:
        AbortSession()(self._session)
        self.app.exit()
