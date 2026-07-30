from textual.content import Content

from keystrike.domain.enums import Mode
from keystrike.domain.models import Keystroke
from keystrike.domain.session import Session
from keystrike.presentation.theme import (
    STYLE_CORRECT,
    STYLE_CORRECTED,
    STYLE_CURRENT,
    STYLE_PENDING,
    STYLE_WRONG_CURRENT,
)
from keystrike.presentation.widgets.typing_area import (
    render_typing_text,
    wrap_typing_text,
)


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


def test_typing_color_constants():
    assert STYLE_PENDING == "white"
    assert STYLE_CORRECT == "grey42"
    assert STYLE_CORRECTED == "dim yellow"
    assert STYLE_CURRENT == "bold underline"


def test_cursor_position_uses_underline_not_block():
    session = _session(position=1)
    assert _style_at(session, 1) == STYLE_CURRENT
    assert "reverse" not in str(_style_at(session, 1))


def test_wrong_keystroke_at_cursor_keeps_underline():
    session = _session(
        position=0,
        keystrokes=[Keystroke(codepoint=ord("a"), typed=ord("x"), t_ns=0, correct=False)],
    )
    assert _style_at(session, 0) == STYLE_WRONG_CURRENT
    assert "underline" in str(_style_at(session, 0))


def test_pending_char_uses_pending_style():
    session = _session(target_text="abc", position=0)
    assert _style_at(session, 1) == STYLE_PENDING
    assert _style_at(session, 2) == STYLE_PENDING


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


def test_space_renders_as_dot_word_divider():
    session = _session(target_text="ab cd", position=0)
    assert render_typing_text(session).plain == "ab·cd"


def test_wrap_breaks_at_word_boundaries():
    session = _session(target_text="hello world foobar", position=0)
    wrapped = wrap_typing_text(render_typing_text(session), 15)
    assert wrapped.plain.split("\n") == ["hello·world·", "foobar"]


def test_textual_render_path_avoids_midword_breaks():
    session = _session(target_text="st series seasons cnasa kterrorist", position=0)
    wrapped = wrap_typing_text(render_typing_text(session), 26)
    content = Content.from_rich_text(wrapped)
    lines = [line.plain for line in content._wrap_and_format(26, overflow="fold")]
    assert lines == ["st·series·seasons·cnasa·", "kterrorist"]
