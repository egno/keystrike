"""The running-session entity — the one deliberately mutable object in the domain.

Everything else in `domain/models.py` is a frozen value object; `Session` tracks
in-progress typing state and is mutated in place by the application-layer use
cases in `application/session_use_cases.py`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .enums import Mode, SessionState
from .models import Keystroke

BACKSPACE = "\x7f"  # normalized backspace codepoint marker used at edges
LEADING_SKIP_KEYS = frozenset(" \t\n\r")  # accidental space/enter/tab before session/word start

LEARN_IDLE_PAUSE_NS = 5 * 1_000_000_000  # pause learn timer after this idle gap


def normalize_newline(char: str, target_char: str) -> str:
    """Treat Enter variants as the target newline when comparing or recording."""
    if char in "\r\n" and target_char in "\r\n":
        return target_char
    return char


def leading_key_char(key: str, character: str | None = None) -> str | None:
    """Map Textual key names to the char checked by ``skip_leading_whitespace``."""
    match key:
        case "space":
            return " "
        case "tab":
            return "\t"
        case "enter":
            return character if character in ("\r", "\n") else "\n"
        case _:
            return None


def skip_leading_whitespace(session: Session, char: str) -> bool:
    """Drop accidental space/enter/tab before session or word start unless they are the target."""
    if not session.target_text or session.position >= len(session.target_text):
        return False
    if char not in LEADING_SKIP_KEYS:
        return False
    target = session.target_text[session.position]
    if normalize_newline(char, target) == target:
        return False
    if session.position == 0:
        return True
    return session.target_text[session.position - 1] in LEADING_SKIP_KEYS


def note_keystroke_for_timer(session: Session, now_ns: int) -> None:
    """Fold inter-keystroke time into active duration (capped at idle threshold)."""
    if session.last_keystroke_at_ns is not None:
        gap = now_ns - session.last_keystroke_at_ns
        session.active_duration_ns += min(gap, LEARN_IDLE_PAUSE_NS)
    session.last_keystroke_at_ns = now_ns


def active_typing_duration_ns(
    session: Session,
    now_ns: int,
    *,
    idle_pause_ns: int = LEARN_IDLE_PAUSE_NS,
) -> int:
    """Active typing time excluding idle gaps longer than ``idle_pause_ns``."""
    if session.typing_started_at_ns is None or session.last_keystroke_at_ns is None:
        return 0
    gap = now_ns - session.last_keystroke_at_ns
    return session.active_duration_ns + min(gap, idle_pause_ns)


def is_typing_idle(
    session: Session,
    now_ns: int,
    *,
    idle_pause_ns: int = LEARN_IDLE_PAUSE_NS,
) -> bool:
    """True once the learn timer would stop counting (gap >= ``idle_pause_ns``)."""
    if session.last_keystroke_at_ns is None:
        return False
    return now_ns - session.last_keystroke_at_ns >= idle_pause_ns


@dataclass(slots=True)
class Session:
    id: str
    target_text: str
    layout: str
    mode: Mode
    lang: str
    started_at_wall: float
    started_at_ns: int            # when the practice screen opened (session creation)
    typing_started_at_ns: int | None = None  # first real keystroke — the timer's true zero
    last_keystroke_at_ns: int | None = None  # wall clock of last real keystroke
    active_duration_ns: int = 0  # accumulated active time between keystrokes
    keystrokes: list[Keystroke] = field(default_factory=list[Keystroke])
    position: int = 0             # index into target_text of the next char to type
    correct_count: int = 0        # total correct keystrokes (does not decrement on backspace)
    total_count: int = 0          # total keystrokes recorded (including errors and corrections)
    error_positions: set[int] = field(default_factory=set[int])  # positions that needed correction
    state: SessionState = SessionState.RUNNING
    focus_key: int | None = None  # adaptive mode: the key this lesson emphasized

    @property
    def finished(self) -> bool:
        return self.position >= len(self.target_text)
