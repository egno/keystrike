import asyncio
from typing import ClassVar

from textual import events
from textual.app import ComposeResult
from textual.binding import BindingType
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Footer, Static

from keystrike.application.advice_runner import AdviceRunner
from keystrike.application.prepare_practice import SessionPrep
from keystrike.domain.models import Bigram, SessionResult
from keystrike.domain.session import leading_key_char, skip_leading_whitespace
from keystrike.presentation.bindings import BACK_BINDINGS
from keystrike.presentation.formatting.trends import format_session_stats_line
from keystrike.presentation.services import PracticeServices
from keystrike.presentation.widgets.advice_panel import AdvicePanel
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
            advice_source=initial.advice_source,
            advice_kinds=initial.advice_kinds,
        )
        self._typing_area = TypingArea(self._session)
        self._hud = HUD(
            self._session,
            get_daily_learn_budget=self._services.get_daily_learn_budget,
            focus_reason=initial.focus_reason,
        )
        self._advice_panel: AdvicePanel | None = None
        self._advice_task: asyncio.Task[None] | None = None

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
            self._advice_panel = AdvicePanel()
            yield self._advice_panel
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
        self._show_stored_advice()
        self.focus()

    def _show_stored_advice(self) -> None:
        """Show the advice that already steers this lesson, so the panel is not
        empty until the first session ends. With no advice yet, say when it comes."""
        panel = self._advice_panel
        runner = self._services.advice_runner
        if panel is None or runner is None:
            return
        if not runner.enabled():
            panel.show_idle()
            return
        stored = runner.current(self._prep.layout)
        label = runner.label(stored.source)
        if stored.actionable or stored.summary:
            panel.show_advice(stored, advisor=label)
        else:
            panel.show_waiting(runner.label())

    async def on_key(self, event: events.Key) -> None:
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
            await self._finish_session()

    async def _finish_session(self) -> None:
        result = self._services.finish(self._session)
        self._services.rebuild_aggregates(result.layout)
        self._refresh_last_session_stats(result)
        await self._request_advice(result.layout)
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

    async def _request_advice(self, layout: str) -> None:
        """Ask the active advisor, and wait for it at most `budget_s` before
        the next lesson is built. A fast advisor steers that lesson; a slow
        one (an LLM) keeps working, the panel shows its advice when it
        arrives, and it steers the lesson after. The runner never cancels a
        request and runs one at a time (sessions that finish meanwhile give
        one follow-up request)."""
        panel = self._advice_panel
        runner = self._services.advice_runner
        if panel is None or runner is None:
            return
        if not runner.enabled():
            panel.show_idle()
            return
        panel.show_thinking(runner.label())
        task = asyncio.get_running_loop().create_task(self._advise(runner, layout, panel))
        self._advice_task = task
        await asyncio.wait({task}, timeout=runner.budget_s)

    @staticmethod
    async def _advise(runner: AdviceRunner, layout: str, panel: AdvicePanel) -> None:
        advice = await runner.request(layout)
        previous = runner.current(layout) if advice.failed else None
        panel.show_advice(advice, previous=previous, advisor=runner.label(advice.source))

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
            advice_source=prep.advice_source,
            advice_kinds=prep.advice_kinds,
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
