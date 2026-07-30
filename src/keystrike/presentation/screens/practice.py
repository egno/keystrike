from typing import ClassVar

from textual import events
from textual.app import ComposeResult
from textual.binding import BindingType
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Footer, Static

from keystrike.application.prepare_practice import SessionPrep
from keystrike.domain.models import SessionResult
from keystrike.domain.session import leading_key_char, skip_leading_whitespace
from keystrike.presentation.bindings import BACK_BINDINGS
from keystrike.presentation.formatting.trends import format_session_stats_line
from keystrike.presentation.services import PracticeServices
from keystrike.presentation.widgets.hud import HUD
from keystrike.presentation.widgets.kb_heatmap import (
    KbHeatmap,
    focus_transition_pair,
    format_focus_note,
)
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
        )
        self._typing_area = TypingArea(self._session)
        self._hud = HUD(
            self._session,
            self._services.clock,
            get_daily_learn_budget=self._services.get_daily_learn_budget,
            focus_reason=initial.focus_reason,
        )

    def compose(self) -> ComposeResult:
        with Vertical():
            yield self._hud
            yield self._typing_area
            if self._prep.layout_obj is not None and self._prep.lesson_heatmap is not None:
                self._kb_heatmap = KbHeatmap(
                    self._prep.layout_obj,
                    self._prep.lesson_heatmap,
                    focus=self._prep.focus_key,
                    urgency=None,
                    focus_transition=focus_transition_pair(self._prep.focus_reason),
                )
                yield self._kb_heatmap
            yield Static(
                self._focus_note_text(),
                id="focus-note",
            )
            yield Static("", id="last-session-stats")
        yield Footer()

    def _focus_note_text(self) -> str:
        return (
            format_focus_note(
                self._prep.focus_key,
                self._prep.focus_reason,
                confidence=self._prep.focus_confidence,
                speed=self._prep.focus_speed,
                accuracy=self._prep.focus_accuracy,
            )
            or ""
        )

    def on_mount(self) -> None:
        self._refresh_focus_note()
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
        self._hud.refresh_display()

        if self._session.finished:
            self._finish_session()

    def _finish_session(self) -> None:
        result = self._services.finish(self._session)
        self._services.rebuild_aggregates(result.layout)
        self._show_last_session_stats(result)
        prep = self._services.prepare_practice()
        if prep is None:
            return
        self._begin_session(prep)

    def _show_last_session_stats(self, result: SessionResult) -> None:
        baseline = self._services.get_session_baseline(result)
        self.query_one("#last-session-stats", Static).update(
            format_session_stats_line(result, baseline=baseline),
        )

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
        )
        self._typing_area.set_session(self._session)
        self._hud.set_session(
            self._session,
            focus_reason=prep.focus_reason,
        )
        KbHeatmap.update_or_none(
            self._kb_heatmap,
            prep.layout_obj,
            prep.lesson_heatmap,
            focus=prep.focus_key,
            urgency=None,
            focus_transition=focus_transition_pair(prep.focus_reason),
        )
        self._refresh_focus_note()

    def action_back(self) -> None:
        self._services.abort(self._session)
        self.app.pop_screen()
