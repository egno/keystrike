from rich.text import Text
from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Static

from keystrike.domain.models import Layout

_ROWS = 3
_COLS = 10
_CONFIDENCE_GOOD = 1.0
_CONFIDENCE_OK = 0.6


def _confidence_style(confidence: float | None) -> str:
    if confidence is None:
        return "grey37"
    if confidence >= _CONFIDENCE_GOOD:
        return "bold green"
    if confidence >= _CONFIDENCE_OK:
        return "yellow"
    return "bold red"


def render_heatmap(layout: Layout, heatmap: dict[int, float]) -> Text:
    """Render the layout's alpha rows as a 3x10 ASCII grid, colored by confidence.

    Staggered (traditional) layouts get a 2-space indent per row, approximating
    the physical row-shift of a regular keyboard. Ortholinear layouts render
    with columns aligned instead — there's no physical stagger to show.
    """
    grid: list[list[tuple[str, str] | None]] = [[None] * _COLS for _ in range(_ROWS)]
    for cp, pos in layout.keys.items():
        if pos.row >= _ROWS:
            continue
        ch = "_" if cp == ord(" ") else chr(cp)
        grid[pos.row][pos.col] = (ch, _confidence_style(heatmap.get(cp)))

    text = Text(no_wrap=True)
    for row_index, row in enumerate(grid):
        if not layout.ortholinear:
            text.append("  " * row_index)
        for cell in row:
            if cell is None:
                text.append("   ")
            else:
                ch, style = cell
                text.append(f" {ch} ", style)
        text.append("\n")
    return text


class KbHeatmap(Widget):
    DEFAULT_CSS = """
    KbHeatmap {
        height: auto;
        padding: 1 2;
    }
    """

    def __init__(self, layout: Layout, heatmap: dict[int, float]) -> None:
        super().__init__()
        self._layout = layout
        self._heatmap = heatmap

    def compose(self) -> ComposeResult:
        yield Static(render_heatmap(self._layout, self._heatmap), id="kb-heatmap-text")
