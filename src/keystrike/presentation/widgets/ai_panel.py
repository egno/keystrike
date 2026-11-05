from __future__ import annotations

from enum import StrEnum

from textual.widgets import Static

from keystrike.domain.ai_models import AiAnalysis


class PanelState(StrEnum):
    IDLE = "idle"  # shows nothing
    ANALYZING = "analyzing"  # placeholder while the model is thinking
    READY = "ready"  # formatted analysis (or the failure note)


def _format_codepoint(value: int) -> str:
    """The character if printable, else its U+ code."""
    ch = chr(value)
    return ch if ch.isprintable() and not ch.isspace() else f"U+{value:04X}"


def _format_key_list(keys: tuple[int, ...]) -> str:
    return ", ".join(_format_codepoint(k) for k in keys)


def build_lines(analysis: AiAnalysis, *, previous: AiAnalysis | None = None) -> list[str]:
    """Panel text. For a failed analysis, `previous` is the advice that stays
    in effect, shown under the error."""
    if analysis.failed:
        if previous is None or previous.failed:
            return [analysis.error]
        return [f"{analysis.error} — keeping the previous advice:", *build_lines(previous)]
    lines: list[str] = []
    if analysis.summary:
        lines.append(analysis.summary)
    if analysis.focus_pair is not None:
        pair = analysis.focus_pair
        lines.append(
            f"Focus: {_format_codepoint(pair.prev_cp)} → {_format_codepoint(pair.next_cp)}"
        )
    elif analysis.focus_key is not None:
        lines.append(f"Focus: {_format_codepoint(analysis.focus_key)}")
    if analysis.emphasis_keys:
        lines.append(f"Practice more: {_format_key_list(analysis.emphasis_keys)}")
    if analysis.rest_keys:
        lines.append(f"Ease up on: {_format_key_list(analysis.rest_keys)}")
    return lines


class AiAnalysisPanel(Static):
    """Displays the AI coach's analysis under the practice area."""

    DEFAULT_CSS = """
    AiAnalysisPanel {
        color: $text-muted;
        padding: 0 2;
        height: auto;
    }
    """

    def __init__(self) -> None:
        # markup=False: the text is model output and may contain "[" sequences.
        super().__init__("", markup=False)
        self._analysis: AiAnalysis | None = None
        self._panel_state = PanelState.IDLE

    @property
    def analysis(self) -> AiAnalysis | None:
        return self._analysis

    @property
    def panel_state(self) -> PanelState:
        return self._panel_state

    def show_idle(self) -> None:
        self._analysis = None
        self._panel_state = PanelState.IDLE
        self.update("")

    def show_analyzing(self) -> None:
        self._panel_state = PanelState.ANALYZING
        self.update("Analyzing…")

    def show_analysis(self, analysis: AiAnalysis, *, previous: AiAnalysis | None = None) -> None:
        self._analysis = analysis
        self._panel_state = PanelState.READY
        self.update("\n".join(build_lines(analysis, previous=previous)))
