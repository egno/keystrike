from dataclasses import dataclass, field

from keystrike.domain.enums import Mode, SessionState
from keystrike.domain.models import Keystroke, SessionResult
from keystrike.domain.null_adapters import NullSessionRepository
from keystrike.domain.protocols import Clock, IdGenerator, SessionRepository
from keystrike.domain.session import BACKSPACE, Session


@dataclass(slots=True)
class StartSession:
    clock: Clock
    id_gen: IdGenerator

    def __call__(
        self,
        target_text: str,
        *,
        layout: str = "qwerty",
        mode: Mode = Mode.FREE,
        lang: str = "en",
        focus_key: int | None = None,
    ) -> Session:
        return Session(
            id=self.id_gen.new_id(),
            target_text=target_text,
            layout=layout,
            mode=mode,
            lang=lang,
            started_at_wall=self.clock.wall_epoch(),
            started_at_ns=self.clock.now_ns(),
            focus_key=focus_key,
        )


@dataclass(slots=True)
class RecordKeystroke:
    """Ingest one keystroke. Returns True if the session is now finished."""

    clock: Clock
    repo: SessionRepository = field(default_factory=NullSessionRepository)

    def backspace(self, session: Session) -> bool:
        return self(session, BACKSPACE)

    def __call__(self, session: Session, char: str) -> bool:
        if session.state is not SessionState.RUNNING:
            return session.finished
        if session.finished:
            return True

        if char == BACKSPACE:
            # Adaptive lessons don't allow correcting mistakes: the confidence
            # engine needs an honest record of what actually happened (keybr
            # does the same) — errors are already captured on the original
            # wrong keystroke, so letting the user erase them would distort it.
            if session.mode is not Mode.ADAPTIVE and session.position > 0:
                session.position -= 1
            # Backspaces are not recorded as Keystrokes in v1 — they just rewind
            # the cursor. Error stats already captured on the original wrong keystroke.
            return session.finished

        # Ignore Enter, Tab, and other multi-char keys unless they are the target
        if len(char) != 1:
            return session.finished

        # The timer doesn't start until the first real keystroke — no penalty
        # for time spent reading the prompt before typing.
        now_ns = self.clock.now_ns()
        if session.typing_started_at_ns is None:
            session.typing_started_at_ns = now_ns
        t_ns = now_ns - session.typing_started_at_ns

        target_cp = ord(session.target_text[session.position])
        typed_cp = ord(char)
        correct = typed_cp == target_cp

        k = Keystroke(codepoint=target_cp, typed=typed_cp, t_ns=t_ns, correct=correct)
        session.keystrokes.append(k)
        session.total_count += 1
        if correct:
            session.correct_count += 1
            session.position += 1
        else:
            session.error_positions.add(session.position)

        self.repo.append_keystroke(session.id, session.started_at_wall, k)

        return session.finished


@dataclass(slots=True)
class FinishSession:
    clock: Clock
    repo: SessionRepository = field(default_factory=NullSessionRepository)

    def __call__(self, session: Session) -> SessionResult:
        session.state = SessionState.COMPLETE
        started_ns = (
            session.typing_started_at_ns
            if session.typing_started_at_ns is not None
            else session.started_at_ns
        )
        duration_ns = self.clock.now_ns() - started_ns

        result = SessionResult(
            schema_version=1,
            session_id=session.id,
            started_at=session.started_at_wall,
            duration_ns=duration_ns,
            layout=session.layout,
            mode=session.mode,
            lesson_alphabet=tuple(sorted({ord(c) for c in session.target_text})),
            focus_key=session.focus_key,
            total_keystrokes=session.total_count,
            correct_keystrokes=session.correct_count,
            lang=session.lang,
        )
        self.repo.save_header(result)
        return result


@dataclass(slots=True)
class AbortSession:
    def __call__(self, session: Session) -> None:
        session.state = SessionState.CANCELLED


def compute_wpm(result: SessionResult) -> float:
    """Standard WPM: (correct_chars / 5) / minutes."""
    minutes = result.duration_ns / 1e9 / 60.0
    if minutes <= 0:
        return 0.0
    return (result.correct_keystrokes / 5.0) / minutes


def compute_accuracy(result: SessionResult) -> float:
    if result.total_keystrokes == 0:
        return 0.0
    return result.correct_keystrokes / result.total_keystrokes


def format_session_stats_line(result: SessionResult) -> str:
    wpm = compute_wpm(result)
    acc = compute_accuracy(result) * 100
    duration = result.duration_ns / 1e9
    return (
        f"Last: WPM [bold]{wpm:5.1f}[/]  "
        f"Acc [bold]{acc:5.1f}%[/]  "
        f"Time [bold]{duration:5.1f}s[/]  "
        f"Keys [bold]{result.total_keystrokes}[/]"
    )
