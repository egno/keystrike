import contextlib
from collections.abc import Callable
from dataclasses import dataclass, field

from keystrike.application.session_queries import (
    compute_accuracy,
    compute_wpm,
    keystrokes_per_word,
    latest_session_header,
    target_speed_cpm,
)
from keystrike.domain.advice import AdvisorCapabilities
from keystrike.domain.aggregate import (
    SessionTiming,
    combine_sessions,
    session_recency_weights,
    tally_session,
)
from keystrike.domain.alphabet_cut import forget_closed_keys
from keystrike.domain.confidence import (
    confidence_of,
    stall_attempts_cap,
    target_ms_per_char,
)
from keystrike.domain.enums import Mode, SessionState
from keystrike.domain.generator import effective_generated_word_bounds
from keystrike.domain.learn_order import keyboard_order
from keystrike.domain.models import (
    Bigram,
    Keystroke,
    Layout,
    SessionResult,
    SessionStats,
    Settings,
)
from keystrike.domain.newest_key import newest_key_gating_cohort
from keystrike.domain.null_adapters import (
    NULL_LAYOUT_REPOSITORY,
    NULL_SETTINGS_REPOSITORY,
    NullSessionRepository,
)
from keystrike.domain.protocols import (
    Clock,
    IdGenerator,
    KeystrokeArchive,
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
        focus_pair: Bigram | None = None,
        advice_source: str | None = None,
        advice_kinds: tuple[str, ...] = (),
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
            focus_pair=focus_pair,
            advice_source=advice_source,
            advice_kinds=advice_kinds,
        )


@dataclass(slots=True)
class RecordKeystroke:
    """Ingest one keystroke. Returns True if the session is now finished."""

    clock: Clock
    layout_repo: LayoutRepository = field(default_factory=lambda: NULL_LAYOUT_REPOSITORY)
    # Layout lookups can hit disk; resolve each layout once for the app's lifetime.
    _layouts: dict[str, Layout] = field(default_factory=dict[str, Layout], init=False)

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

        key_pos = self._layout(session.layout).keys.get(target_cp)

        k = Keystroke(
            codepoint=target_cp,
            typed=typed_cp,
            t_ns=t_ns,
            correct=correct,
            finger=key_pos.finger if key_pos else None,
            hand=key_pos.hand if key_pos else None,
        )
        session.keystrokes.append(k)
        session.total_count += 1
        if correct:
            session.correct_count += 1
            session.position += 1
        else:
            session.error_positions.add(session.position)

        return session.finished

    def _layout(self, name: str) -> Layout:
        layout = self._layouts.get(name)
        if layout is None:
            layout = self._layouts[name] = self.layout_repo.get(name)
        return layout


@dataclass(frozen=True, slots=True)
class _DraftTiming:
    """Minimal `SessionTiming` for an in-progress session not yet persisted as
    a `SessionResult` — only what `combine_sessions` actually reads."""

    started_at: float
    duration_ns: int


def _snapshot_finish_state(
    session: Session,
    duration_ns: int,
    stats: SessionStats,
    *,
    repo: SessionRepository,
    settings_repo: SettingsRepository,
    layout_repo: LayoutRepository,
) -> tuple[tuple[int, ...], dict[int, float], tuple[Bigram, ...]]:
    """Unlocked keys, their confidence, and the newest key's gate cohort
    after this session."""
    settings = settings_repo.load()
    layout = layout_repo.get(session.layout)
    draft = _DraftTiming(started_at=session.started_at_wall, duration_ns=duration_ns)
    prior_headers = sorted(
        repo.iter_headers(session.layout),
        key=lambda h: h.started_at,
    )[-(settings.confidence_session_window - 1) :]
    order = keyboard_order(layout)
    sessions: list[tuple[SessionTiming, SessionStats]] = [
        (
            header,
            forget_closed_keys(header.stats, header.started_at, order, settings.alphabet_cuts),
        )
        for header in prior_headers
    ]
    sessions.append((draft, stats))
    combined = combine_sessions(sessions)
    target = target_ms_per_char(target_speed_cpm(repo, settings, session.layout))
    unlocked = compute_unlocked(
        order,
        settings.alphabet_size,
        combined.keys,
        target,
        tuning=settings.unlock,
        transitions=combined.transitions,
        transition_stall_attempts_cap=stall_attempts_cap(
            settings.unlock.min_transition_confidence_attempts
        ),
    )
    key_confidence = {
        cp: confidence_of(
            cp, combined.keys, target, min_attempts=settings.unlock.min_confidence_attempts
        )
        for cp in unlocked
    }
    cohort = newest_key_gating_cohort(
        unlocked, combined.keys, limit=settings.unlock.gating_bigram_limit
    )
    return unlocked, key_confidence, cohort


def _keep_pairs(stats: SessionStats, pairs: set[Bigram]) -> SessionStats:
    return SessionStats(
        keys=stats.keys,
        transitions={pair: t for pair, t in stats.transitions.items() if pair in pairs},
    )


def _recent_session_ids(repo: SessionRepository, window: int) -> set[str]:
    """Ids of the newest `window` sessions of every layout."""
    by_layout: dict[str, list[SessionResult]] = {}
    for header in repo.iter_all_headers():
        by_layout.setdefault(header.layout, []).append(header)
    keep: set[str] = set()
    for headers in by_layout.values():
        headers.sort(key=lambda h: h.started_at, reverse=True)
        keep.update(h.session_id for h in headers[: max(1, window)])
    return keep


@dataclass(slots=True)
class FinishSession:
    clock: Clock
    repo: SessionRepository = field(default_factory=NullSessionRepository)
    settings_repo: SettingsRepository = NULL_SETTINGS_REPOSITORY
    layout_repo: LayoutRepository = NULL_LAYOUT_REPOSITORY
    # Raw keystrokes are archived only while the active advisor needs them,
    # and only for the sessions inside each layout's confidence window.
    keystroke_archive: KeystrokeArchive | None = None
    advisor_capabilities: Callable[[], AdvisorCapabilities] = AdvisorCapabilities

    def __call__(self, session: Session) -> SessionResult:
        session.state = SessionState.COMPLETE
        duration_ns = (
            active_typing_duration_ns(session, self.clock.now_ns())
            if session.typing_started_at_ns is not None
            else 0
        )

        settings = self.settings_repo.load()
        goal_cpm = target_speed_cpm(self.repo, settings, session.layout)
        stats = tally_session(session.keystrokes)
        unlocked_keys, key_confidence, cohort = _snapshot_finish_state(
            session,
            duration_ns,
            stats,
            repo=self.repo,
            settings_repo=self.settings_repo,
            layout_repo=self.layout_repo,
        )
        # Only the pairs the next lessons read are saved: the newest key's gate
        # cohort and this lesson's focus pair. This keeps each row small as
        # the alphabet grows.
        kept = set(cohort)
        if session.focus_pair is not None:
            kept.add(session.focus_pair)
        stats = _keep_pairs(stats, kept)
        # alphabet_size growth is persisted by BuildLesson right before the
        # next lesson is generated (see alphabet_sync.sync_alphabet_size),
        # not here -- syncing it immediately on every session finish caused
        # a distracting mid-flow status jump before the next word list.

        generated_min_len, generated_max_len = effective_generated_word_bounds(
            settings.word_gen.min_len,
            settings.word_gen.max_len,
        )
        words_completed = count_words_completed(session.target_text, session.position)
        minutes = duration_ns / 1e9 / 60.0
        result = SessionResult(
            schema_version=5,
            session_id=session.id,
            started_at=session.started_at_wall,
            duration_ns=duration_ns,
            layout=session.layout,
            mode=session.mode,
            lesson_alphabet=tuple(sorted({ord(c) for c in session.target_text})),
            focus_key=session.focus_key,
            focus_pair=session.focus_pair,
            advice_source=session.advice_source,
            advice_kinds=session.advice_kinds,
            total_keystrokes=session.total_count,
            correct_keystrokes=session.correct_count,
            words_completed=words_completed,
            lang=session.lang,
            unlocked_keys=unlocked_keys,
            key_confidence=key_confidence,
            target_speed_cpm=goal_cpm,
            generated_min_len=generated_min_len,
            generated_max_len=generated_max_len,
            cpm=session.position / minutes if minutes > 0 else 0.0,
            wpm=words_completed / minutes if minutes > 0 else 0.0,
            stats=stats,
        )
        self.repo.save_header(result)
        self._archive_keystrokes(session, settings)
        return result

    def _archive_keystrokes(self, session: Session, settings: Settings) -> None:
        archive = self.keystroke_archive
        if archive is None:
            return
        keep = self.advisor_capabilities().needs_keystrokes
        # best-effort: an archive failure must not lose the session
        with contextlib.suppress(OSError):
            if not keep:
                archive.clear()
                return
            archive.save(
                session.id,
                session.keystrokes,
                layout=session.layout,
                started_at=session.started_at_wall,
                ended_at=self.clock.wall_epoch(),
            )
            archive.prune(_recent_session_ids(self.repo, settings.confidence_session_window))


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


@dataclass(slots=True)
class GetLatestSessionHeader:
    repo: SessionRepository

    def __call__(self, layout: str) -> SessionResult | None:
        return latest_session_header(self.repo, layout)


@dataclass(slots=True)
class GetKeystrokesPerWord:
    """Measured keystrokes per word for WPM <-> CPM display (see
    `session_queries.keystrokes_per_word`)."""

    repo: SessionRepository = field(default_factory=NullSessionRepository)

    def __call__(self, settings: Settings) -> float:
        return keystrokes_per_word(self.repo, settings)
