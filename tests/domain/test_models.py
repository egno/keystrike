import pytest

from keystrike.domain.enums import Finger, Hand, Mode, SessionState
from keystrike.domain.models import KeyPos, Keystroke, Layout, SessionResult


def test_keystroke_is_frozen():
    k = Keystroke(codepoint=ord("a"), typed=ord("a"), t_ns=1000, correct=True)
    with pytest.raises(AttributeError):
        k.correct = False  # type: ignore[misc]


def test_session_result_alphabet_is_tuple():
    r = SessionResult(
        schema_version=1,
        session_id="x",
        started_at=0.0,
        duration_ns=1,
        layout="qwerty",
        mode=Mode.ADAPTIVE,
        lesson_alphabet=(ord("a"), ord("b")),
        focus_key=None,
        total_keystrokes=0,
        correct_keystrokes=0,
    )
    assert isinstance(r.lesson_alphabet, tuple)


def test_keypos_defaults_to_unshifted():
    kp = KeyPos(codepoint=ord("a"), row=2, col=1, finger=Finger.PINKY, hand=Hand.L)
    assert kp.shifted is False


def test_session_state_enum():
    assert SessionState.RUNNING != SessionState.COMPLETE


def test_layout_defaults_to_staggered():
    layout = Layout(name="x", keys={}, learn_order=())
    assert layout.ortholinear is False
