from rich.text import Text
from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Static

from keystrike.domain.models import Layout

_ROWS = 3
_COLS = 10
_CONFIDENCE_GOOD = 1.0
_CONFIDENCE_OK = 0.6
_FOCUS_STYLE = "bold underline cyan"
_REVIEW_STYLE = "underline magenta"


def _confidence_style(confidence: float | None) -> str:
    if confidence is None:
        return "grey37"
    if confidence >= _CONFIDENCE_GOOD:
        return "bold green"
    if confidence >= _CONFIDENCE_OK:
        return "yellow"
    return "bold red"


def _key_style(
    confidence: float | None,
    urgency: float,
    *,
    is_focus: bool,
) -> str:
    if is_focus:
        return _FOCUS_STYLE
    style = _confidence_style(confidence)
    if urgency > 0:
        style = f"{style} {_REVIEW_STYLE}"
    return style


def render_heatmap(
    layout: Layout,
    heatmap: dict[int, float],
    focus: int | None = None,
    urgency: dict[int, float] | None = None,
) -> Text:
    """Render the layout's alpha rows as a 3x10 ASCII grid, colored by confidence.

    Staggered (traditional) layouts get a 2-space indent per row, approximating
    the physical row-shift of a regular keyboard. Ortholinear layouts render
    with columns aligned instead — there's no physical stagger to show.

    `focus`, if given, overrides that one key's style regardless of its
    confidence — used by Practice to call out today's lesson's focus letter
    among the (otherwise identically-styled) unlocked keys.

    Keys with review urgency > 0 get a magenta underline on top of their
    confidence color so stale-but-mastered keys stand apart from merely weak ones.
    """
    grid: list[list[tuple[str, str] | None]] = [[None] * _COLS for _ in range(_ROWS)]
    for cp, pos in layout.keys.items():
        if pos.row >= _ROWS:
            continue
        ch = "_" if cp == ord(" ") else chr(cp)
        style = _key_style(
            heatmap.get(cp),
            (urgency or {}).get(cp, 0.0),
            is_focus=(cp == focus),
        )
        grid[pos.row][pos.col] = (ch, style)

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

    def __init__(
        self,
        layout: Layout,
        heatmap: dict[int, float],
        focus: int | None = None,
        urgency: dict[int, float] | None = None,
    ) -> None:
        super().__init__()
        self._layout = layout
        self._heatmap = heatmap
        self._focus = focus
        self._urgency = urgency

    def compose(self) -> ComposeResult:
        yield Static(
            render_heatmap(self._layout, self._heatmap, self._focus, self._urgency),
            id="kb-heatmap-text",
        )

    def refresh_heatmap(
        self,
        layout: Layout,
        heatmap: dict[int, float],
        focus: int | None = None,
        urgency: dict[int, float] | None = None,
    ) -> None:
        self._layout = layout
        self._heatmap = heatmap
        self._focus = focus
        self._urgency = urgency
        self.query_one("#kb-heatmap-text", Static).update(
            render_heatmap(layout, heatmap, focus, urgency),
        )
