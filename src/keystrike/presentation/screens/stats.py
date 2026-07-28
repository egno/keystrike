from typing import ClassVar, Literal

from textual import events
from textual.app import ComposeResult
from textual.binding import BindingType
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Footer, Static

from keystrike.application.session_use_cases import (
    compute_accuracy,
    compute_wpm,
    format_focus_confidence_trend_line,
    format_key_confidence_trend_line,
    format_wpm_trend_line,
)
from keystrike.application.stats_use_cases import GetHeatmap, GetHistory
from keystrike.domain.models import Layout, SessionResult
from keystrike.domain.protocols import LayoutRepository, StatsRebuilder
from keystrike.presentation.bindings import BACK_BINDINGS
from keystrike.presentation.widgets.kb_heatmap import KbHeatmap

_View = Literal["overview", "key_detail"]


class StatsScreen(Screen[None]):
    DEFAULT_CSS = """
    StatsScreen > Vertical {
        padding: 1 2;
    }
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        *BACK_BINDINGS,
    ]

    def __init__(
        self,
        *,
        layout: str,
        layout_repo: LayoutRepository,
        rebuild_aggregates: StatsRebuilder,
        get_heatmap: GetHeatmap,
        get_history: GetHistory,
    ) -> None:
        super().__init__()
        self._layout_name = layout
        self._layout_repo = layout_repo
        self._rebuild_aggregates = rebuild_aggregates
        self._get_heatmap = get_heatmap
        self._get_history = get_history
        self._view: _View = "overview"
        self._selected_cp: int | None = None
        self._layout: Layout | None = None
        self._heatmap_confidence: dict[int, float] = {}
        self._heatmap_urgency: dict[int, float] = {}
        self._trend_history: list[SessionResult] = []
        self._kb_heatmap: KbHeatmap | None = None

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(f"[bold]Stats - {self._layout_name}[/]", id="stats-title")
            yield Static("", id="stats-wpm-trend")
            yield Static("", id="stats-focus-confidence")
            yield Static("", id="stats-key-detail")
            yield Static("[dim]Loading...[/]", id="stats-history")
        yield Footer()

    def on_mount(self) -> None:
        self.focus()
        self._rebuild_aggregates(self._layout_name)
        heatmap_view = self._get_heatmap(self._layout_name)
        layout = self._layout_repo.get(self._layout_name)
        self._layout = layout
        self._heatmap_confidence = heatmap_view.confidence
        self._heatmap_urgency = heatmap_view.urgency

        title = f"[bold]Stats - {self._layout_name}[/]"
        if layout.ortholinear:
            title += "  [dim](ortholinear)[/]"
        self.query_one("#stats-title", Static).update(title)

        self._kb_heatmap = KbHeatmap(
            layout, heatmap_view.confidence, urgency=heatmap_view.urgency,
        )
        self.query_one(Vertical).mount(self._kb_heatmap, before="#stats-history")

        self._trend_history = self._get_history(self._layout_name, limit=20)
        self._render_overview()

        history = self._get_history(self._layout_name, limit=10)
        lines = [
            f"{i + 1:>2}. wpm {compute_wpm(h):5.1f}  acc {compute_accuracy(h) * 100:5.1f}%"
            for i, h in enumerate(history)
        ]
        self.query_one("#stats-history", Static).update(
            "\n".join(lines) if lines else "[dim]No sessions yet for this layout.[/]"
        )
        self.query_one("#stats-key-detail", Static).display = False

    def on_key(self, event: events.Key) -> None:
        codepoint = self._codepoint_from_key(event)
        if codepoint is None:
            return
        event.stop()
        self._show_key_detail(codepoint)

    def action_back(self) -> None:
        if self._view == "key_detail":
            self._show_overview()
            return
        self.app.pop_screen()

    def _codepoint_from_key(self, event: events.Key) -> int | None:
        if self._layout is None:
            return None
        if event.key == "space":
            codepoint = ord(" ")
        elif (
            event.character is not None
            and len(event.character) == 1
            and event.character.isprintable()
        ):
            codepoint = ord(event.character)
        else:
            return None
        if codepoint not in self._layout.keys:
            return None
        return codepoint

    def _render_overview(self) -> None:
        wpm_line = format_wpm_trend_line(self._trend_history)
        self.query_one("#stats-wpm-trend", Static).update(
            wpm_line if wpm_line else "[dim]No sessions yet for WPM trend.[/]"
        )

        focus_line = format_focus_confidence_trend_line(self._trend_history)
        self.query_one("#stats-focus-confidence", Static).update(
            focus_line if focus_line else "[dim]No sessions yet for focus confidence.[/]"
        )

    def _show_overview(self) -> None:
        self._view = "overview"
        self._selected_cp = None
        self.query_one("#stats-wpm-trend", Static).display = True
        self.query_one("#stats-focus-confidence", Static).display = True
        self.query_one("#stats-history", Static).display = True
        self.query_one("#stats-key-detail", Static).display = False
        if self._kb_heatmap is not None and self._layout is not None:
            self._kb_heatmap.refresh_heatmap(
                self._layout,
                self._heatmap_confidence,
                urgency=self._heatmap_urgency,
            )

    def _show_key_detail(self, codepoint: int) -> None:
        self._view = "key_detail"
        self._selected_cp = codepoint
        self.query_one("#stats-wpm-trend", Static).display = False
        self.query_one("#stats-focus-confidence", Static).display = False
        self.query_one("#stats-history", Static).display = False
        cumulative = self._heatmap_confidence.get(codepoint)
        detail_line = format_key_confidence_trend_line(
            self._trend_history,
            codepoint,
            cumulative=cumulative,
        )
        key_detail = self.query_one("#stats-key-detail", Static)
        key_detail.update(
            detail_line if detail_line else "[dim]No sessions yet for this key.[/]"
        )
        key_detail.display = True
        if self._kb_heatmap is not None and self._layout is not None:
            self._kb_heatmap.refresh_heatmap(
                self._layout,
                self._heatmap_confidence,
                focus=codepoint,
                urgency=self._heatmap_urgency,
            )
