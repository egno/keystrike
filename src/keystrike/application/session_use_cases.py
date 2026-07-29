from collections.abc import Sequence
from dataclasses import dataclass, field, replace

from keystrike.domain.aggregate import aggregate_session, combine_sessions
from keystrike.domain.confidence import (
    compute_unlocked,
    confidence_of,
    target_ms_per_char,
)
from keystrike.domain.enums import Mode, SessionState
from keystrike.domain.generator import typical_chars_per_word
from keystrike.domain.learn_order import keyboard_order
from keystrike.domain.models import Keystroke, SessionResult
from keystrike.domain.null_adapters import NullSessionRepository
from keystrike.domain.protocols import (
    AggregatesCache,
    Clock,
    IdGenerator,
    LayoutRepository,
    SessionRepository,
    SettingsRepository,
)
from keystrike.domain.session import BACKSPACE, Session

_SPARK = "▁▂▃▄▅▆▇█"


@dataclass(slots=True)
class StartSession:
    clock: Clock
    id_gen: IdGenerator

    def __call__(
        self,
        target_text: str,
        *,
        layout: str = "qwerty",
        mode: Mode = Mode.ADAPTIVE,
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


def _snapshot_unlock_state(
    session: Session,
    duration_ns: int,
    *,
    repo: SessionRepository,
    settings_repo: SettingsRepository,
    layout_repo: LayoutRepository,
) -> tuple[tuple[int, ...], dict[int, float]]:
    settings = settings_repo.load()
    layout = layout_repo.get(session.layout)
    draft = SessionResult(
        schema_version=3,
        session_id=session.id,
        started_at=session.started_at_wall,
        duration_ns=duration_ns,
        layout=session.layout,
        mode=session.mode,
        lesson_alphabet=(),
        focus_key=session.focus_key,
        total_keystrokes=session.total_count,
        correct_keystrokes=session.correct_count,
        lang=session.lang,
    )
    prior_headers = sorted(
        repo.iter_headers(session.layout),
        key=lambda h: h.started_at,
    )[-(settings.confidence_session_window - 1):]
    sessions = [
        (header, repo.load_keystrokes(header.session_id)) for header in prior_headers
    ]
    sessions.append((draft, session.keystrokes))
    stats = combine_sessions(sessions).keys
    target = target_ms_per_char(settings.target_speed_cpm)
    unlocked = compute_unlocked(
        keyboard_order(layout),
        settings.alphabet_size,
        stats,
        target,
        min_attempts=settings.min_confidence_attempts,
    )
    return unlocked, {
        cp: confidence_of(cp, stats, target, min_attempts=settings.min_confidence_attempts)
        for cp in unlocked
    }


def _sync_alphabet_size(unlocked_keys: tuple[int, ...], settings_repo: SettingsRepository) -> None:
    """Keep settings.alphabet_size at least as large as the current unlock set."""
    if not unlocked_keys:
        return
    settings = settings_repo.load()
    unlocked_count = len(unlocked_keys)
    if unlocked_count > settings.alphabet_size:
        settings_repo.save(replace(settings, alphabet_size=unlocked_count))


@dataclass(slots=True)
class FinishSession:
    clock: Clock
    repo: SessionRepository = field(default_factory=NullSessionRepository)
    aggregates_cache: AggregatesCache | None = None
    settings_repo: SettingsRepository | None = None
    layout_repo: LayoutRepository | None = None

    def __call__(self, session: Session) -> SessionResult:
        session.state = SessionState.COMPLETE
        started_ns = (
            session.typing_started_at_ns
            if session.typing_started_at_ns is not None
            else session.started_at_ns
        )
        duration_ns = self.clock.now_ns() - started_ns

        target_speed_cpm = 0
        unlocked_keys: tuple[int, ...] = ()
        key_confidence: dict[int, float] = {}
        if (
            self.settings_repo is not None
            and self.layout_repo is not None
        ):
            settings = self.settings_repo.load()
            target_speed_cpm = settings.target_speed_cpm
            unlocked_keys, key_confidence = _snapshot_unlock_state(
                session,
                duration_ns,
                repo=self.repo,
                settings_repo=self.settings_repo,
                layout_repo=self.layout_repo,
            )
            _sync_alphabet_size(unlocked_keys, self.settings_repo)

        result = SessionResult(
            schema_version=3,
            session_id=session.id,
            started_at=session.started_at_wall,
            duration_ns=duration_ns,
            layout=session.layout,
            mode=session.mode,
            lesson_alphabet=tuple(sorted({ord(c) for c in session.target_text})),
            focus_key=session.focus_key,
            total_keystrokes=session.total_count,
            correct_keystrokes=session.correct_count,
            words_completed=count_words_completed(session.target_text, session.position),
            lang=session.lang,
            unlocked_keys=unlocked_keys,
            key_confidence=key_confidence,
            target_speed_cpm=target_speed_cpm,
        )
        self.repo.save_header(result)
        return result


@dataclass(slots=True)
class AbortSession:
    def __call__(self, session: Session) -> None:
        session.state = SessionState.CANCELLED


def count_words_completed(text: str, position: int) -> int:
    """Words fully typed in text[:position] (trailing space or EOF counts the last word)."""
    if position <= 0:
        return 0
    if position >= len(text):
        return len(text.split())
    if text[position] == " ":
        return len(text[:position].split())
    if " " not in text[:position]:
        return 0
    return text[:position].count(" ")


def compute_cpm(result: SessionResult) -> float:
    """Correct characters per minute."""
    minutes = result.duration_ns / 1e9 / 60.0
    if minutes <= 0:
        return 0.0
    return result.correct_keystrokes / minutes


def _words_for_wpm(result: SessionResult) -> float:
    if result.words_completed > 0:
        return float(result.words_completed)
    if result.correct_keystrokes <= 0:
        return 0.0
    # Legacy sessions without words_completed: estimate from char count.
    return result.correct_keystrokes / typical_chars_per_word()


def compute_wpm(result: SessionResult) -> float:
    """Words per minute from completed lesson words, not chars/5."""
    minutes = result.duration_ns / 1e9 / 60.0
    if minutes <= 0:
        return 0.0
    return _words_for_wpm(result) / minutes


def compute_accuracy(result: SessionResult) -> float:
    if result.total_keystrokes == 0:
        return 0.0
    return result.correct_keystrokes / result.total_keystrokes


def value_sparkline(values: Sequence[float]) -> str:
    """Unicode sparkline for numeric values, oldest→newest."""
    if not values:
        return ""
    lo, hi = min(values), max(values)
    if hi == lo:
        level = len(_SPARK) - 1 if hi > 0 else 0
        return _SPARK[level] * len(values)
    span = hi - lo
    return "".join(
        _SPARK[min(len(_SPARK) - 1, int((v - lo) / span * (len(_SPARK) - 1)))]
        for v in values
    )


def wpm_sparkline(headers: Sequence[SessionResult], *, limit: int = 20) -> str:
    """Unicode sparkline of WPM per session, oldest→newest."""
    ordered = sorted(headers, key=lambda h: h.started_at)[-limit:]
    if not ordered:
        return ""
    return value_sparkline([compute_wpm(h) for h in ordered])


def _display_confidence(
    stored_conf: float,
    stored_target_cpm: int,
    current_target_cpm: int,
) -> float:
    if stored_target_cpm <= 0 or current_target_cpm <= 0:
        return stored_conf
    return stored_conf * (
        target_ms_per_char(current_target_cpm)
        / target_ms_per_char(stored_target_cpm)
    )


def focus_confidence_values(
    headers: Sequence[SessionResult],
    *,
    limit: int = 20,
    current_target_speed_cpm: int = 0,
) -> list[float]:
    ordered = sorted(headers, key=lambda h: h.started_at)[-limit:]
    return [
        _display_confidence(
            h.key_confidence.get(h.focus_key, 0.0) if h.focus_key is not None else 0.0,
            h.target_speed_cpm,
            current_target_speed_cpm,
        )
        for h in ordered
    ]


def focus_confidence_sparkline(
    headers: Sequence[SessionResult],
    *,
    limit: int = 20,
    current_target_speed_cpm: int = 0,
) -> str:
    """Unicode sparkline of focus-key confidence per session, oldest→newest."""
    values = focus_confidence_values(
        headers, limit=limit, current_target_speed_cpm=current_target_speed_cpm,
    )
    if not values:
        return ""
    return value_sparkline(values)


def key_confidence_values(
    headers: Sequence[SessionResult],
    codepoint: int,
    *,
    limit: int = 20,
    current_target_speed_cpm: int = 0,
) -> list[float]:
    ordered = sorted(headers, key=lambda h: h.started_at)[-limit:]
    return [
        _display_confidence(
            h.key_confidence.get(codepoint, 0.0),
            h.target_speed_cpm,
            current_target_speed_cpm,
        )
        for h in ordered
    ]


def key_confidence_sparkline(
    headers: Sequence[SessionResult],
    codepoint: int,
    *,
    limit: int = 20,
    current_target_speed_cpm: int = 0,
) -> str:
    values = key_confidence_values(
        headers, codepoint, limit=limit, current_target_speed_cpm=current_target_speed_cpm,
    )
    if not values:
        return ""
    return value_sparkline(values)


def _char_label(codepoint: int) -> str:
    ch = chr(codepoint)
    return ch if ch.isprintable() and not ch.isspace() else f"U+{codepoint:04X}"


def _focus_char_label(focus_key: int | None) -> str:
    if focus_key is None:
        return "?"
    return _char_label(focus_key)


def format_wpm_trend_line(headers: Sequence[SessionResult], *, limit: int = 20) -> str:
    ordered = sorted(headers, key=lambda h: h.started_at)[-limit:]
    if not ordered:
        return ""
    wpms = [compute_wpm(h) for h in ordered]
    spark = wpm_sparkline(headers, limit=limit)
    return (
        f"[bold]WPM trend[/] ({len(wpms)} sessions)  {spark}  "
        f"[dim]latest {wpms[-1]:.0f}  peak {max(wpms):.0f}[/]"
    )


def format_focus_confidence_trend_line(
    headers: Sequence[SessionResult],
    *,
    limit: int = 20,
    current_target_speed_cpm: int = 0,
) -> str:
    ordered = sorted(headers, key=lambda h: h.started_at)[-limit:]
    if not ordered:
        return ""
    values = focus_confidence_values(
        headers, limit=limit, current_target_speed_cpm=current_target_speed_cpm,
    )
    spark = focus_confidence_sparkline(
        headers, limit=limit, current_target_speed_cpm=current_target_speed_cpm,
    )
    label = _focus_char_label(ordered[-1].focus_key)
    return (
        f"[bold]Focus '{label}' confidence[/] ({len(values)} sessions)  {spark}  "
        f"[dim]latest {values[-1]:.2f}  peak {max(values):.2f}[/]"
    )


def format_key_confidence_trend_line(
    headers: Sequence[SessionResult],
    codepoint: int,
    *,
    limit: int = 20,
    current_target_speed_cpm: int = 0,
    cumulative: float | None = None,
) -> str:
    ordered = sorted(headers, key=lambda h: h.started_at)[-limit:]
    if not ordered:
        return ""
    values = key_confidence_values(
        headers, codepoint, limit=limit, current_target_speed_cpm=current_target_speed_cpm,
    )
    spark = key_confidence_sparkline(
        headers, codepoint, limit=limit, current_target_speed_cpm=current_target_speed_cpm,
    )
    label = _char_label(codepoint)
    line = (
        f"[bold]'{label}' confidence[/] ({len(values)} sessions)  {spark}  "
        f"[dim]latest {values[-1]:.2f}  peak {max(values):.2f}[/]"
    )
    if cumulative is not None:
        line += f"  [dim]cumulative {cumulative:.2f}[/]"
    return line


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
