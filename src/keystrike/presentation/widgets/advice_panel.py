from __future__ import annotations

from enum import StrEnum

from textual.widgets import Static

from keystrike.domain.advice import Kind, LessonAdvice, Recommendation, format_char


class PanelState(StrEnum):
    IDLE = "idle"  # shows nothing
    WAITING = "waiting"  # an advisor is on, but there is no advice yet
    THINKING = "thinking"  # placeholder while the advisor is thinking
    READY = "ready"  # formatted advice (or the failure note)


WAITING_TEXT = "No advice yet — it appears after your first session."


def _keys(keys: tuple[int, ...]) -> str:
    return ", ".join(format_char(k) for k in keys)


def _line(rec: Recommendation) -> str:
    """One recommendation: what, why, and what supports it."""
    ev = rec.evidence
    why = rec.reason.value
    if ev.opportunities:
        why += f", {ev.events} of {ev.opportunities}"
    match rec.kind:
        case Kind.FOCUS:
            what = f"Focus: {_keys(rec.keys)}"
        case Kind.FOCUS_PAIR:
            what = f"Focus: {format_char(rec.keys[0])} → {format_char(rec.keys[1])}"
        case Kind.EMPHASIZE:
            what = f"Practice more: {_keys(rec.keys)}"
        case Kind.EASE:
            what = f"Ease up on: {_keys(rec.keys)}"
        case Kind.CONTRAST:
            what = f"Tell apart: {format_char(rec.keys[0])} / {format_char(rec.keys[1])}"
    return f"{what} ({why})"


def advisor_line(advisor: str) -> str:
    return f"Advisor: {advisor}"


def build_lines(
    advice: LessonAdvice, *, previous: LessonAdvice | None = None, advisor: str = ""
) -> list[str]:
    """Panel text, under an `Advisor: <name>` line when `advisor` is given.
    For a failed advice, `previous` is the advice that stays in effect, shown
    under the error."""
    header = [advisor_line(advisor)] if advisor else []
    if advice.failed:
        if previous is None or previous.failed:
            return [*header, advice.error]
        return [
            *header,
            f"{advice.error} — keeping the previous advice:",
            *build_lines(previous),
        ]
    lines: list[str] = header
    if advice.summary:
        lines.append(advice.summary)
    lines.extend(_line(rec) for rec in advice.recommendations)
    return lines


class AdvicePanel(Static):
    """Displays the active advisor's advice under the practice area."""

    DEFAULT_CSS = """
    AdvicePanel {
        color: $text-muted;
        padding: 0 2;
        height: auto;
    }
    """

    def __init__(self) -> None:
        # markup=False: the text is advisor output and may contain "[" sequences.
        super().__init__("", markup=False)
        self._advice: LessonAdvice | None = None
        self._advisor = ""
        self._panel_state = PanelState.IDLE

    @property
    def advice(self) -> LessonAdvice | None:
        return self._advice

    @property
    def advisor(self) -> str:
        """The advisor named in the panel ("" when none is shown)."""
        return self._advisor

    @property
    def panel_state(self) -> PanelState:
        return self._panel_state

    def show_idle(self) -> None:
        self._advice = None
        self._advisor = ""
        self._panel_state = PanelState.IDLE
        self.update("")

    def _show(self, advisor: str, *body: str) -> None:
        self._advisor = advisor
        header = [advisor_line(advisor)] if advisor else []
        self.update("\n".join([*header, *body]))

    def show_waiting(self, advisor: str = "") -> None:
        self._advice = None
        self._panel_state = PanelState.WAITING
        self._show(advisor, WAITING_TEXT)

    def show_thinking(self, advisor: str = "") -> None:
        self._panel_state = PanelState.THINKING
        self._show(advisor, "Thinking…")

    def show_advice(
        self,
        advice: LessonAdvice,
        *,
        previous: LessonAdvice | None = None,
        advisor: str = "",
    ) -> None:
        self._advice = advice
        self._advisor = advisor
        self._panel_state = PanelState.READY
        self.update("\n".join(build_lines(advice, previous=previous, advisor=advisor)))
