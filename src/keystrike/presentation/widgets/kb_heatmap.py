from dataclasses import dataclass

from rich.text import Text
from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Static

from keystrike.domain.confidence import CONFIDENCE_GOOD
from keystrike.domain.enums import FocusKind
from keystrike.domain.focus import FocusReason
from keystrike.domain.models import Bigram, Layout

_ROWS = 3
_COLS = 10
_CONFIDENCE_OK = 0.6
_FOCUS_MASTERED_STYLE = "underline cyan"
_FOCUS_STYLE = "underline"
_REVIEW_STYLE = "underline magenta"


def focus_transition_pair(focus_reason: FocusReason | None) -> Bigram | None:
    """The bigram a transition-kind focus reason is about, or None for a
    key-kind reason (or no reason at all)."""
    if focus_reason is None or not focus_reason.is_transition:
        return None
    return focus_reason.pair


_FULL_REASON_WORD = {"wk": "weak", "cal": "calibrating", "rev": "review"}


def focus_reason_label_short(focus_reason: FocusReason) -> str:
    """Compact HUD/note label: wk, cal, rev."""
    match focus_reason.kind:
        case FocusKind.KEY_WEAK | FocusKind.TRANSITION_WEAK:
            return "wk"
        case FocusKind.KEY_CALIBRATING | FocusKind.TRANSITION_CALIBRATING:
            return "cal"
        case FocusKind.KEY_REVIEW | FocusKind.TRANSITION_REVIEW:
            return "rev"


def focus_reason_label(focus_reason: FocusReason) -> str:
    """Full display text for a focus reason (wiki/docs). UI uses
    `focus_reason_label_short` instead."""
    word = _FULL_REASON_WORD[focus_reason_label_short(focus_reason)]
    if focus_reason.is_transition:
        assert focus_reason.pair is not None
        return f"{focus_reason.pair.chars()} {word} transition"
    return word


def _confidence_style(confidence: float | None) -> str:
    if confidence is None:
        return "grey37"
    if confidence >= CONFIDENCE_GOOD:
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
    style = _confidence_style(confidence)
    if urgency > 0:
        style = f"{style} {_REVIEW_STYLE}"
    if is_focus:
        focus_style = (
            _FOCUS_MASTERED_STYLE
            if confidence is not None and confidence >= CONFIDENCE_GOOD
            else _FOCUS_STYLE
        )
        style = f"{style} {focus_style}"
    return style


@dataclass(frozen=True, slots=True)
class HeatmapDisplay:
    """Everything needed to render/refresh a keyboard heatmap, bundled so it
    travels as one value instead of five loose, always-parallel parameters."""

    layout: Layout
    heatmap: dict[int, float]
    focus: int | None = None
    urgency: dict[int, float] | None = None
    focus_transition: tuple[int, int] | None = None


def build_heatmap_display(
    layout: Layout | None,
    heatmap: dict[int, float] | None,
    *,
    focus: int | None = None,
    urgency: dict[int, float] | None = None,
    focus_transition: tuple[int, int] | None = None,
) -> HeatmapDisplay | None:
    """`HeatmapDisplay(...)`, or None if the layout/heatmap data isn't ready yet."""
    if layout is None or heatmap is None:
        return None
    return HeatmapDisplay(
        layout,
        heatmap,
        focus=focus,
        urgency=urgency,
        focus_transition=focus_transition,
    )


def render_heatmap(display: HeatmapDisplay) -> Text:
    """Render the layout's alpha rows as a 3x10 ASCII grid, colored by confidence.

    Staggered (traditional) layouts get a 2-space indent per row, approximating
    the physical row-shift of a regular keyboard. Ortholinear layouts render
    with columns aligned instead — there's no physical stagger to show.

    `display.focus`, if given, adds an underline on top of the key's confidence
    color — cyan when mastered (confidence >= 1.0), plain underline when still
    weak. Used by Practice to call out today's lesson focus without hiding
    yellow/red.

    Keys with review urgency > 0 get a magenta underline on top of their
    confidence color so stale-but-mastered keys stand apart from merely weak ones.
    """
    layout = display.layout
    heatmap = display.heatmap
    focus = display.focus
    urgency = display.urgency
    focus_transition = display.focus_transition

    grid: list[list[tuple[str, str] | None]] = [[None] * _COLS for _ in range(_ROWS)]
    for cp, pos in layout.keys.items():
        if pos.row >= _ROWS:
            continue
        ch = "_" if cp == ord(" ") else chr(cp)
        is_focus = cp == focus or (focus_transition is not None and cp in focus_transition)
        style = _key_style(
            heatmap.get(cp),
            (urgency or {}).get(cp, 0.0),
            is_focus=is_focus,
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


def format_focus_note(
    focus_key: int | None,
    focus_reason: FocusReason | None,
    *,
    confidence: float | None = None,
    speed: float | None = None,
    accuracy: float | None = None,
    attempts: int | None = None,
    min_attempts: int | None = None,
) -> str | None:
    if focus_key is None or focus_reason is None:
        return None
    transition = focus_transition_pair(focus_reason)
    subject = transition.chars() if transition is not None else chr(focus_key)
    reason = focus_reason_label_short(focus_reason)
    if (
        focus_reason.kind in (FocusKind.KEY_CALIBRATING, FocusKind.TRANSITION_CALIBRATING)
        and attempts is not None
        and min_attempts is not None
    ):
        reason = f"{reason} {attempts}/{min_attempts}"
    parts = [subject, reason]
    if speed is not None:
        parts.append(f"{speed:.2f}")
    if accuracy is not None:
        parts.append(f"{accuracy * 100:.0f}%")
    conf_s = f"{confidence:.2f}" if confidence is not None else "0.00"
    parts.append(conf_s)
    return f"[dim]{' · '.join(parts)}[/]"


class KbHeatmap(Widget):
    DEFAULT_CSS = """
    KbHeatmap {
        height: auto;
        padding: 1 2;
    }
    """

    def __init__(self, display: HeatmapDisplay) -> None:
        super().__init__()
        self._display = display

    def compose(self) -> ComposeResult:
        yield Static(render_heatmap(self._display), id="kb-heatmap-text")

    def refresh_heatmap(self, display: HeatmapDisplay) -> None:
        self._display = display
        self.query_one("#kb-heatmap-text", Static).update(render_heatmap(display))

    @staticmethod
    def update_or_none(widget: "KbHeatmap | None", display: HeatmapDisplay | None) -> None:
        """Refresh `widget` if it and the required layout/heatmap data are present.

        Centralizes the "if self._kb_heatmap is not None and display present"
        guard that would otherwise be duplicated at every call site.
        """
        if widget is None or display is None:
            return
        widget.refresh_heatmap(display)
