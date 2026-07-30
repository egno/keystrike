from typing import ClassVar, Literal

from textual import events
from textual.app import ComposeResult
from textual.binding import BindingType
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Footer, Static

from keystrike.application.stats_use_cases import HeatmapView
from keystrike.domain.models import Layout, SessionResult
from keystrike.presentation.bindings import BACK_BINDINGS
from keystrike.presentation.formatting.trends import (
    char_label,
    format_aggregate_metric_trend_block,
    format_focus_confidence_trend_line,
    format_key_metric_trend_block,
)
from keystrike.presentation.services import StatsServices
from keystrike.presentation.widgets.kb_heatmap import (
    HeatmapDisplay,
    KbHeatmap,
    build_heatmap_display,
)

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
        services: StatsServices,
        current_target_speed_cpm: int = 0,
        confidence_session_window: int = 10,
    ) -> None:
        super().__init__()
        self._layout_name = layout
        self._services = services
        self._current_target_speed_cpm = current_target_speed_cpm
        self._confidence_session_window = confidence_session_window
        self._view: _View = "overview"
        self._layout: Layout | None = None
        self._heatmap: HeatmapView | None = None
        self._trend_history: list[SessionResult] = []
        self._kb_heatmap: KbHeatmap | None = None

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(f"[bold]Stats — {self._layout_name}[/]", id="stats-title")
            yield Static("", id="stats-trends")
        yield Footer()

    def on_mount(self) -> None:
        self.focus()
        self._services.rebuild_aggregates(self._layout_name)
        heatmap_view = self._services.get_heatmap(self._layout_name)
        layout = self._services.layout_repo.get(self._layout_name)
        self._layout = layout
        self._heatmap = heatmap_view

        title = f"[bold]Stats — {self._layout_name}[/]"
        if layout.ortholinear:
            title += "  [dim](ortholinear)[/]"
        self.query_one("#stats-title", Static).update(title)

        self._kb_heatmap = KbHeatmap(
            HeatmapDisplay(layout, heatmap_view.confidence, urgency=heatmap_view.urgency)
        )
        self.query_one(Vertical).mount(
            Static("[dim]vs current goal[/]", id="stats-heatmap-caption"),
            Static(
                "[dim]Press a key on the heatmap for letter stats · Esc to return[/]",
                id="stats-heatmap-hint",
            ),
            self._kb_heatmap,
        )

        self._trend_history = self._services.get_history(
            self._layout_name,
            limit=self._confidence_session_window,
        )
        self._render_overview()

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
        widget = self.query_one("#stats-trends", Static)
        limit = self._confidence_session_window
        confidence_values, speed_values, accuracy_values = (
            self._services.get_aggregate_metric_trends(
                self._layout_name,
                current_target_speed_cpm=self._current_target_speed_cpm,
            )
        )
        layout_block = format_aggregate_metric_trend_block(
            title="Layout",
            confidence_values=confidence_values,
            speed_values=speed_values,
            accuracy_values=accuracy_values,
            limit=limit,
        )
        focus_line = format_focus_confidence_trend_line(
            self._trend_history,
            limit=limit,
            current_target_speed_cpm=self._current_target_speed_cpm,
        )
        parts = [block for block in (layout_block, focus_line) if block]
        widget.update("\n\n".join(parts) if parts else "[dim]No sessions yet for this layout.[/]")

    def _render_key_detail(self, codepoint: int) -> None:
        widget = self.query_one("#stats-trends", Static)
        limit = self._confidence_session_window
        speed_values, accuracy_values = self._services.get_key_metric_trends(
            self._layout_name,
            codepoint,
            current_target_speed_cpm=self._current_target_speed_cpm,
        )
        label = char_label(codepoint)
        detail = format_key_metric_trend_block(
            title=f"'{label}'",
            headers=self._trend_history,
            codepoint=codepoint,
            speed_values=speed_values,
            accuracy_values=accuracy_values,
            limit=limit,
            current_target_speed_cpm=self._current_target_speed_cpm,
        )
        widget.update(detail if detail else "[dim]No sessions yet for this key.[/]")

    def _show_overview(self) -> None:
        self._view = "overview"
        self._render_overview()
        KbHeatmap.update_or_none(
            self._kb_heatmap,
            build_heatmap_display(
                self._layout,
                self._heatmap.confidence if self._heatmap is not None else None,
                urgency=self._heatmap.urgency if self._heatmap is not None else None,
            ),
        )

    def _show_key_detail(self, codepoint: int) -> None:
        self._view = "key_detail"
        self._render_key_detail(codepoint)
        KbHeatmap.update_or_none(
            self._kb_heatmap,
            build_heatmap_display(
                self._layout,
                self._heatmap.confidence if self._heatmap is not None else None,
                focus=codepoint,
                urgency=self._heatmap.urgency if self._heatmap is not None else None,
            ),
        )
