from collections.abc import Iterable
from dataclasses import dataclass, field, replace

from keystrike.domain.aggregate import combine_sessions, session_recency_weights
from keystrike.domain.confidence import (
    confidence_of,
    target_ms_per_char,
)
from keystrike.domain.enums import Mode, SessionState
from keystrike.domain.generator import typical_chars_per_word
from keystrike.domain.learn_order import keyboard_order
from keystrike.domain.models import Keystroke, SessionResult
from keystrike.domain.null_adapters import (
    NULL_LAYOUT_REPOSITORY,
    NULL_SETTINGS_REPOSITORY,
    NullSessionRepository,
)
from keystrike.domain.protocols import (
    Clock,
    IdGenerator,
    LayoutRepository,
    SessionRepository,
    SettingsRepository,
)
from keystrike.domain.session import (
    BACKSPACE,
    Session,
    active_typing_duration_ns,
    normalize_newline,
    note_keystroke_for_timer,
    skip_leading_whitespace,
)
from keystrike.domain.unlock import compute_unlocked


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

        if skip_leading_whitespace(session, char):
            return session.finished

        # The timer doesn't start until the first real keystroke — no penalty
        # for time spent reading the prompt before typing.
        now_ns = self.clock.now_ns()
        if session.typing_started_at_ns is None:
            session.typing_started_at_ns = now_ns
        note_keystroke_for_timer(session, now_ns)
        t_ns = active_typing_duration_ns(session, now_ns)

        target_char = session.target_text[session.position]
        char = normalize_newline(char, target_char)
        target_cp = ord(target_char)
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
    )[-(settings.confidence_session_window - 1) :]
    sessions: list[tuple[SessionResult, Iterable[Keystroke]]] = [
        (header, repo.load_keystrokes(header.session_id)) for header in prior_headers
    ]
    sessions.append((draft, session.keystrokes))
    combined = combine_sessions(sessions)
    target = target_ms_per_char(settings.target_speed_cpm)
    unlocked = compute_unlocked(
        keyboard_order(layout),
        settings.alphabet_size,
        combined.keys,
        target,
        min_attempts=settings.min_confidence_attempts,
        transitions=combined.transitions,
        min_transition_attempts=settings.min_transition_confidence_attempts,
    )
    return unlocked, {
        cp: confidence_of(cp, combined.keys, target, min_attempts=settings.min_confidence_attempts)
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
    settings_repo: SettingsRepository = NULL_SETTINGS_REPOSITORY
    layout_repo: LayoutRepository = NULL_LAYOUT_REPOSITORY

    def __call__(self, session: Session) -> SessionResult:
        session.state = SessionState.COMPLETE
        duration_ns = (
            active_typing_duration_ns(session, self.clock.now_ns())
            if session.typing_started_at_ns is not None
            else 0
        )

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
        self.repo.append_keystrokes(session.id, session.started_at_wall, session.keystrokes)
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


def previous_session_header(
    repo: SessionRepository,
    result: SessionResult,
) -> SessionResult | None:
    """Session immediately before ``result`` for the same layout, if any."""
    ordered = sorted(repo.iter_headers(result.layout), key=lambda h: h.started_at)
    for i, header in enumerate(ordered):
        if header.session_id == result.session_id:
            return ordered[i - 1] if i > 0 else None
    return None


@dataclass(frozen=True, slots=True)
class SessionStatsBaseline:
    wpm: float
    accuracy_pct: float


def confidence_window_session_baseline(
    repo: SessionRepository,
    result: SessionResult,
    *,
    window: int,
) -> SessionStatsBaseline | None:
    """Recency-weighted WPM/accuracy from prior sessions in the confidence window.

    Uses the same sliding window as ``GetKeyMetricTrends`` and
    ``_snapshot_unlock_state``, excluding ``result`` itself.
    """
    ordered = sorted(repo.iter_headers(result.layout), key=lambda h: h.started_at)
    for i, header in enumerate(ordered):
        if header.session_id != result.session_id:
            continue
        prior = ordered[max(0, i - window + 1) : i]
        if not prior:
            return None
        weights = session_recency_weights(len(prior))
        total = sum(weights)
        wpm = sum(compute_wpm(h) * w for h, w in zip(prior, weights, strict=True)) / total
        acc = (
            sum(compute_accuracy(h) * 100 * w for h, w in zip(prior, weights, strict=True)) / total
        )
        return SessionStatsBaseline(wpm=wpm, accuracy_pct=acc)
    return None


@dataclass(slots=True)
class GetSessionBaseline:
    """Recency-weighted WPM/accuracy baseline for a just-finished session.

    Wraps ``confidence_window_session_baseline`` behind its own collaborators
    so callers (e.g. ``PracticeScreen``) don't need to reach into another use
    case's private ``repo``/``settings_repo`` to compute it.
    """

    repo: SessionRepository
    settings_repo: SettingsRepository = NULL_SETTINGS_REPOSITORY

    def __call__(self, result: SessionResult) -> SessionStatsBaseline | None:
        window = self.settings_repo.load().confidence_session_window
        return confidence_window_session_baseline(self.repo, result, window=window)
