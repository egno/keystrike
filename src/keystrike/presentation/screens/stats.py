from typing import ClassVar, Literal

from textual import events
from textual.app import ComposeResult
from textual.binding import BindingType
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Footer, Static

from keystrike.application.session_use_cases import (
    format_focus_confidence_trend_line,
    format_metric_trend_block,
)
from keystrike.application.stats_use_cases import (
    GetAggregateMetricTrends,
    GetHeatmap,
    GetHistory,
    GetKeyMetricTrends,
)
from keystrike.domain.models import Layout, SessionResult
from keystrike.domain.protocols import LayoutRepository, StatsRebuilder
from keystrike.presentation.bindings import BACK_BINDINGS
from keystrike.presentation.widgets.kb_heatmap import KbHeatmap

_View = Literal["overview", "key_detail"]


def _char_label(codepoint: int) -> str:
    ch = chr(codepoint)
    return ch if ch.isprintable() and not ch.isspace() else f"U+{codepoint:04X}"


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
        get_key_metric_trends: GetKeyMetricTrends,
        get_aggregate_metric_trends: GetAggregateMetricTrends,
        current_target_speed_cpm: int = 0,
        confidence_session_window: int = 10,
    ) -> None:
        super().__init__()
        self._layout_name = layout
        self._layout_repo = layout_repo
        self._rebuild_aggregates = rebuild_aggregates
        self._get_heatmap = get_heatmap
        self._get_history = get_history
        self._get_key_metric_trends = get_key_metric_trends
        self._get_aggregate_metric_trends = get_aggregate_metric_trends
        self._current_target_speed_cpm = current_target_speed_cpm
        self._confidence_session_window = confidence_session_window
        self._view: _View = "overview"
        self._selected_cp: int | None = None
        self._layout: Layout | None = None
        self._heatmap_confidence: dict[int, float] = {}
        self._heatmap_urgency: dict[int, float] = {}
        self._trend_history: list[SessionResult] = []
        self._kb_heatmap: KbHeatmap | None = None

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(f"[bold]Stats — {self._layout_name}[/]", id="stats-title")
            yield Static("", id="stats-trends")
        yield Footer()

    def on_mount(self) -> None:
        self.focus()
        self._rebuild_aggregates(self._layout_name)
        heatmap_view = self._get_heatmap(self._layout_name)
        layout = self._layout_repo.get(self._layout_name)
        self._layout = layout
        self._heatmap_confidence = heatmap_view.confidence
        self._heatmap_urgency = heatmap_view.urgency

        title = f"[bold]Stats — {self._layout_name}[/]"
        if layout.ortholinear:
            title += "  [dim](ortholinear)[/]"
        self.query_one("#stats-title", Static).update(title)

        self._kb_heatmap = KbHeatmap(
            layout, heatmap_view.confidence, urgency=heatmap_view.urgency,
        )
        self.query_one(Vertical).mount(
            Static("[dim]vs current goal[/]", id="stats-heatmap-caption"),
            Static(
                "[dim]Press a key on the heatmap for letter stats · Esc to return[/]",
                id="stats-heatmap-hint",
            ),
            self._kb_heatmap,
        )

        self._trend_history = self._get_history(
            self._layout_name, limit=self._confidence_session_window,
        )
        self._render_trends(mode="overview")

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

    def _render_trends(self, *, mode: _View, codepoint: int | None = None) -> None:
        widget = self.query_one("#stats-trends", Static)
        limit = self._confidence_session_window
        if mode == "overview":
            confidence_values, speed_values, accuracy_values = (
                self._get_aggregate_metric_trends(
                    self._layout_name,
                    current_target_speed_cpm=self._current_target_speed_cpm,
                )
            )
            layout_block = format_metric_trend_block(
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
            widget.update(
                "\n\n".join(parts) if parts
                else "[dim]No sessions yet for this layout.[/]"
            )
            return

        assert codepoint is not None
        speed_values, accuracy_values = self._get_key_metric_trends(
            self._layout_name,
            codepoint,
            current_target_speed_cpm=self._current_target_speed_cpm,
        )
        label = _char_label(codepoint)
        detail = format_metric_trend_block(
            title=f"'{label}'",
            headers=self._trend_history,
            codepoint=codepoint,
            speed_values=speed_values,
            accuracy_values=accuracy_values,
            limit=limit,
            current_target_speed_cpm=self._current_target_speed_cpm,
        )
        widget.update(
            detail if detail else "[dim]No sessions yet for this key.[/]"
        )

    def _show_overview(self) -> None:
        self._view = "overview"
        self._selected_cp = None
        self._render_trends(mode="overview")
        if self._kb_heatmap is not None and self._layout is not None:
            self._kb_heatmap.refresh_heatmap(
                self._layout,
                self._heatmap_confidence,
                urgency=self._heatmap_urgency,
            )

    def _show_key_detail(self, codepoint: int) -> None:
        self._view = "key_detail"
        self._selected_cp = codepoint
        self._render_trends(mode="key_detail", codepoint=codepoint)
        if self._kb_heatmap is not None and self._layout is not None:
            self._kb_heatmap.refresh_heatmap(
                self._layout,
                self._heatmap_confidence,
                focus=codepoint,
                urgency=self._heatmap_urgency,
            )
