import asyncio
from typing import ClassVar

from textual import events
from textual.app import ComposeResult
from textual.binding import BindingType
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Footer, Static

from keystrike.application.prepare_practice import SessionPrep
from keystrike.domain.ai_models import AiAnalysis
from keystrike.domain.models import Bigram, SessionResult
from keystrike.domain.session import leading_key_char, skip_leading_whitespace
from keystrike.presentation.bindings import BACK_BINDINGS
from keystrike.presentation.formatting.trends import format_session_stats_line
from keystrike.presentation.services import PracticeServices
from keystrike.presentation.widgets.ai_panel import AiAnalysisPanel
from keystrike.presentation.widgets.hud import HUD
from keystrike.presentation.widgets.kb_heatmap import (
    HeatmapDisplay,
    KbHeatmap,
    build_heatmap_display,
    focus_transition_pair,
    format_focus_note,
)
from keystrike.presentation.widgets.typing_area import TypingArea


def format_bigram_calibration(progress: tuple[int, int] | None) -> str | None:
    if progress is None:
        return None
    return f"[dim]Bigram calibration: {progress[0]}/{progress[1]} ready[/]"


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
    PracticeScreen #focus-note {
        color: $text-muted;
        padding: 0 2;
        height: auto;
    }
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        *BACK_BINDINGS,
    ]

    def __init__(
        self,
        *,
        services: PracticeServices,
        initial: SessionPrep,
    ) -> None:
        super().__init__()
        self._services = services
        self._prep = initial
        self._kb_heatmap: KbHeatmap | None = None
        self._session = self._services.start(
            initial.target_text,
            layout=initial.layout,
            mode=initial.mode,
            focus_key=initial.focus_key,
            focus_pair=initial.focus_pair,
        )
        self._typing_area = TypingArea(self._session)
        self._hud = HUD(
            self._session,
            get_daily_learn_budget=self._services.get_daily_learn_budget,
            focus_reason=initial.focus_reason,
        )
        self._ai_panel: AiAnalysisPanel | None = None
        self._ai_running = False
        self._ai_pending: str | None = None

    def compose(self) -> ComposeResult:
        with Vertical():
            yield self._hud
            yield self._typing_area
            if self._prep.layout_obj is not None and self._prep.lesson_heatmap is not None:
                display = self._current_heatmap_display(
                    focus=self._prep.focus_key,
                    focus_transition=focus_transition_pair(self._prep.focus_reason),
                )
                if display is not None:
                    self._kb_heatmap = KbHeatmap(display)
                    yield self._kb_heatmap
            yield Static(
                self._focus_note_text(),
                id="focus-note",
            )
            yield Static("", id="last-session-stats")
            self._ai_panel = AiAnalysisPanel()
            yield self._ai_panel
        yield Footer()

    def _focus_note_text(self) -> str:
        focus_note = format_focus_note(
            self._prep.focus_key,
            self._prep.focus_reason,
            confidence=self._prep.focus_confidence,
            speed=self._prep.focus_speed,
            accuracy=self._prep.focus_accuracy,
            attempts=self._prep.focus_attempts,
            min_attempts=self._prep.focus_min_attempts,
        )
        calibration = self._prep.bigram_calibration
        progress_note = format_bigram_calibration(calibration)
        return "\n".join(note for note in (focus_note, progress_note) if note)

    def _current_heatmap_display(
        self,
        *,
        focus: int | None = None,
        focus_transition: Bigram | None = None,
    ) -> HeatmapDisplay | None:
        """Build heatmap display using current session's layout and heatmap."""
        return build_heatmap_display(
            self._prep.layout_obj,
            self._prep.lesson_heatmap,
            focus=focus,
            focus_transition=focus_transition,
        )

    def on_mount(self) -> None:
        self._refresh_focus_note()
        self._refresh_last_session_stats()
        self.focus()

    def on_key(self, event: events.Key) -> None:
        key = event.key
        char: str | None = event.character

        leading = leading_key_char(key, char)
        if leading is not None and skip_leading_whitespace(self._session, leading):
            event.stop()
            return

        if key == "backspace":
            self._services.record.backspace(self._session)
        elif key == "space":
            self._services.record(self._session, " ")
        elif char is not None and len(char) == 1 and char.isprintable():
            self._services.record(self._session, char)
        else:
            return

        event.stop()
        self._typing_area.refresh_display()

        if self._session.finished:
            self._finish_session()

    def _finish_session(self) -> None:
        result = self._services.finish(self._session)
        self._services.rebuild_aggregates(result.layout)
        self._refresh_last_session_stats(result)
        self._start_ai_analysis(result)
        prep = self._services.prepare_practice()
        if prep is None:
            return
        self._begin_session(prep)

    def _refresh_last_session_stats(self, result: SessionResult | None = None) -> None:
        header = result or self._services.get_latest_session_header(self._prep.layout)
        widget = self.query_one("#last-session-stats", Static)
        if header is None:
            widget.update("")
            return
        baseline = self._services.get_session_baseline(header)
        widget.update(format_session_stats_line(header, baseline=baseline))

    def _start_ai_analysis(self, result: SessionResult) -> None:
        """Kick off the AI coach in the background; the panel shows the outcome.

        The next lesson starts immediately and uses the previous analysis (see
        `AiAnalyzer.suggestion`); this one lands for the lesson after. Only one
        request runs at a time: sessions finished meanwhile are folded into a
        single follow-up request, so a slow model still answers (cancelling
        it on every session would mean it never does) and its replies arrive
        in order."""
        panel = self._ai_panel
        analyzer = self._services.ai_analyzer
        if panel is None or analyzer is None or self._services.get_history is None:
            return
        if not analyzer.enabled():
            panel.show_idle()
            return
        panel.show_analyzing()
        if self._ai_running:
            self._ai_pending = result.layout
            return
        self._ai_running = True
        self.run_worker(
            self._analyze_until_idle(result.layout),
            group="ai-analysis",
            exit_on_error=False,
        )

    async def _analyze_until_idle(self, layout: str) -> None:
        next_layout: str | None = layout
        try:
            while next_layout is not None:
                self._ai_pending = None
                await self._analyze(next_layout)
                next_layout = self._ai_pending
                if next_layout is not None and self._ai_panel is not None:
                    self._ai_panel.show_analyzing()
        finally:
            self._ai_running = False
            self._ai_pending = None

    async def _analyze(self, layout: str) -> None:
        analyzer = self._services.ai_analyzer
        get_history = self._services.get_history
        panel = self._ai_panel
        if analyzer is None or get_history is None or panel is None:
            return
        # The just-finished session is already saved, so it is in the history.
        try:
            history = await asyncio.to_thread(get_history, layout, analyzer.window())
            analysis = await analyzer.analyze(layout, history)
        except Exception as exc:
            analysis = AiAnalysis(
                layout=layout, error=f"AI analysis unavailable ({type(exc).__name__})"
            )
        previous = analyzer.latest(layout) if analysis.failed else None
        panel.show_analysis(analysis, previous=previous)

    def _refresh_focus_note(self) -> None:
        note = self.query_one("#focus-note", Static)
        text = self._focus_note_text()
        note.update(text)
        note.display = bool(text)

    def _begin_session(self, prep: SessionPrep) -> None:
        self._prep = prep
        self._session = self._services.start(
            prep.target_text,
            layout=prep.layout,
            mode=prep.mode,
            focus_key=prep.focus_key,
            focus_pair=prep.focus_pair,
        )
        self._typing_area.set_session(self._session)
        self._hud.set_session(
            self._session,
            focus_reason=prep.focus_reason,
        )
        KbHeatmap.update_or_none(
            self._kb_heatmap,
            self._current_heatmap_display(
                focus=prep.focus_key,
                focus_transition=focus_transition_pair(prep.focus_reason),
            ),
        )
        self._refresh_focus_note()

    def action_back(self) -> None:
        self._services.abort(self._session)
        self.app.pop_screen()
