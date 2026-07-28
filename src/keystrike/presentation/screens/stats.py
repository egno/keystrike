from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import BindingType
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Footer, Static

from keystrike.application.session_use_cases import compute_accuracy, compute_wpm
from keystrike.application.stats_use_cases import GetHeatmap, GetHistory
from keystrike.domain.protocols import LayoutRepository, StatsRebuilder
from keystrike.presentation.bindings import BACK_BINDINGS
from keystrike.presentation.widgets.kb_heatmap import KbHeatmap


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

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(f"[bold]Stats — {self._layout_name}[/]", id="stats-title")
            yield Static("[dim]Loading…[/]", id="stats-history")
        yield Footer()

    def on_mount(self) -> None:
        self._rebuild_aggregates(self._layout_name)
        heatmap_view = self._get_heatmap(self._layout_name)
        layout = self._layout_repo.get(self._layout_name)

        title = f"[bold]Stats — {self._layout_name}[/]"
        if layout.ortholinear:
            title += "  [dim](ortholinear)[/]"
        self.query_one("#stats-title", Static).update(title)

        self.query_one(Vertical).mount(
            KbHeatmap(layout, heatmap_view.confidence, urgency=heatmap_view.urgency),
            before="#stats-history",
        )

        history = self._get_history(self._layout_name, limit=10)
        lines = [
            f"{i + 1:>2}. wpm {compute_wpm(h):5.1f}  acc {compute_accuracy(h) * 100:5.1f}%"
            for i, h in enumerate(history)
        ]
        self.query_one("#stats-history", Static).update(
            "\n".join(lines) if lines else "[dim]No sessions yet for this layout.[/]"
        )

    def action_back(self) -> None:
        self.app.pop_screen()
