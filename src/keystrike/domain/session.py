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
