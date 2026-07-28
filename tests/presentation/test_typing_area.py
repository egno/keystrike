from keystrike.domain.enums import Mode
from keystrike.domain.models import Keystroke
from keystrike.domain.session import Session
from keystrike.presentation.theme import STYLE_CORRECT, STYLE_CORRECTED
from keystrike.presentation.widgets.typing_area import render_typing_text


def _session(
    *,
    target_text: str = "abc",
    position: int = 0,
    keystrokes: list[Keystroke] | None = None,
    error_positions: set[int] | None = None,
) -> Session:
    return Session(
        id="s1",
        target_text=target_text,
        layout="qwerty",
        mode=Mode.ADAPTIVE,
        lang="en",
        started_at_wall=0.0,
        started_at_ns=0,
        keystrokes=keystrokes or [],
        position=position,
        error_positions=error_positions or set(),
    )


def _style_at(session: Session, index: int) -> object:
    text = render_typing_text(session)
    span = next(s for s in text.spans if s.start == index)
    return span.style


def test_clean_correct_char_uses_correct_style():
    session = _session(position=1)
    assert _style_at(session, 0) == STYLE_CORRECT


def test_corrected_char_uses_corrected_style():
    session = _session(
        position=1,
        error_positions={0},
        keystrokes=[Keystroke(codepoint=ord("a"), typed=ord("x"), t_ns=0, correct=False)],
    )
    assert _style_at(session, 0) == STYLE_CORRECTED
