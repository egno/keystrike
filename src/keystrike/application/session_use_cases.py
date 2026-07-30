from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field, replace

from keystrike.domain.aggregate import combine_sessions, session_recency_weights
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
from keystrike.domain.session import (
    BACKSPACE,
    Session,
    active_typing_duration_ns,
    normalize_newline,
    note_keystroke_for_timer,
    skip_leading_whitespace,
)

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
    )[-(settings.confidence_session_window - 1):]
    sessions: list[tuple[SessionResult, Iterable[Keystroke]]] = [
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
        duration_ns = (
            active_typing_duration_ns(session, self.clock.now_ns())
            if session.typing_started_at_ns is not None
            else 0
        )

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
        for k in session.keystrokes:
            self.repo.append_keystroke(session.id, session.started_at_wall, k)
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
    focus_key = ordered[-1].focus_key
    if focus_key is None:
        return ""
    values = key_confidence_values(
        headers,
        focus_key,
        limit=limit,
        current_target_speed_cpm=current_target_speed_cpm,
    )
    label = _focus_char_label(focus_key)
    return format_metric_trend_block(
        title=f"Focus '{label}'",
        confidence_values=values,
        speed_values=[],
        accuracy_values=[],
        limit=limit,
    )


# Keep in sync with presentation/theme.py STYLE_TREND_* / STYLE_DELTA_*.
_TREND_CONFIDENCE_COLOR = "cyan"
_TREND_SPEED_COLOR = "green"
_TREND_ACCURACY_COLOR = "yellow"
_DELTA_IMPROVE_COLOR = "green"
_DELTA_REGRESS_COLOR = "red"


def _colored_sparkline(spark: str, color: str) -> str:
    return f"[{color}]{spark}[/]" if spark else ""


def _default_metric_value(value: float) -> str:
    return f"{value:.2f}"


_GRID_LABEL_WIDTH = 10
_GRID_VALUE_WIDTH = 8


def _format_metric_trend_line(
    label: str,
    color: str,
    values: Sequence[float],
    spark: str,
    *,
    format_value: Callable[[float], str] | None = None,
    suffix: str = "",
    show_sessions: bool = True,
    grid: bool = False,
    spark_width: int = 20,
) -> str:
    if not values:
        return ""
    fmt = format_value or _default_metric_value
    label_text = label.ljust(_GRID_LABEL_WIDTH) if grid else label
    spark_text = spark.ljust(spark_width) if grid else spark
    session_part = f" ({len(values)} sessions)  " if show_sessions else "  "
    latest_str = fmt(values[-1])
    peak_str = fmt(max(values))
    if grid:
        values_part = (
            f"latest {latest_str:>{_GRID_VALUE_WIDTH}}  "
            f"peak {peak_str:>{_GRID_VALUE_WIDTH}}"
        )
    else:
        values_part = f"latest {latest_str}  peak {peak_str}"
    line = (
        f"[bold {color}]{label_text}[/]{session_part}"
        f"{_colored_sparkline(spark_text, color)}  "
        f"[dim {color}]{values_part}[/]"
    )
    if suffix:
        line += f"  {suffix}"
    return line


def format_confidence_trend_line(
    values: Sequence[float],
    *,
    grid: bool = False,
    spark_width: int = 20,
) -> str:
    return _format_metric_trend_line(
        "confidence",
        _TREND_CONFIDENCE_COLOR,
        values,
        value_sparkline(values),
        show_sessions=not grid,
        grid=grid,
        spark_width=spark_width,
    )


def format_key_confidence_trend_line(
    headers: Sequence[SessionResult],
    codepoint: int,
    *,
    limit: int = 20,
    current_target_speed_cpm: int = 0,
    cumulative: float | None = None,
    include_key_name: bool = True,
    grid: bool = False,
    spark_width: int = 20,
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
    char = _char_label(codepoint)
    label = f"'{char}' confidence" if include_key_name else "confidence"
    suffix = ""
    if cumulative is not None:
        suffix = f"[dim {_TREND_CONFIDENCE_COLOR}]cumulative {cumulative:.2f}[/]"
    return _format_metric_trend_line(
        label,
        _TREND_CONFIDENCE_COLOR,
        values,
        spark,
        suffix=suffix,
        show_sessions=not grid,
        grid=grid,
        spark_width=spark_width,
    )


def format_key_speed_trend_line(
    values: Sequence[float],
    *,
    grid: bool = False,
    spark_width: int = 20,
) -> str:
    return _format_metric_trend_line(
        "speed",
        _TREND_SPEED_COLOR,
        values,
        value_sparkline(values),
        show_sessions=not grid,
        grid=grid,
        spark_width=spark_width,
    )


def format_key_accuracy_trend_line(
    values: Sequence[float],
    *,
    grid: bool = False,
    spark_width: int = 20,
) -> str:
    pct_values = [v * 100 for v in values]
    return _format_metric_trend_line(
        "accuracy",
        _TREND_ACCURACY_COLOR,
        pct_values,
        value_sparkline(pct_values),
        format_value=lambda v: f"{v:.1f}%",
        show_sessions=not grid,
        grid=grid,
        spark_width=spark_width,
    )


def format_metric_trend_block(
    title: str,
    *,
    speed_values: Sequence[float],
    accuracy_values: Sequence[float],
    limit: int = 20,
    confidence_values: Sequence[float] | None = None,
    headers: Sequence[SessionResult] | None = None,
    codepoint: int | None = None,
    current_target_speed_cpm: int = 0,
    cumulative: float | None = None,
) -> str:
    grid = True
    spark_width = limit
    if headers is not None and codepoint is not None:
        ordered = sorted(headers, key=lambda h: h.started_at)[-limit:]
        session_count = len(ordered) if ordered else max(
            len(speed_values), len(accuracy_values), 0,
        )
        conf_line = format_key_confidence_trend_line(
            headers,
            codepoint,
            limit=limit,
            current_target_speed_cpm=current_target_speed_cpm,
            cumulative=cumulative,
            include_key_name=False,
            grid=grid,
            spark_width=spark_width,
        )
    else:
        session_count = max(
            len(confidence_values or []),
            len(speed_values),
            len(accuracy_values),
            0,
        )
        conf_line = format_confidence_trend_line(
            confidence_values or [],
            grid=grid,
            spark_width=spark_width,
        )
    header = f"[bold]{title}[/]"
    if session_count:
        header += f" ({session_count} sessions)"
    else:
        return ""
    lines = [
        header,
        conf_line,
        format_key_speed_trend_line(
            speed_values, grid=grid, spark_width=spark_width,
        ),
        format_key_accuracy_trend_line(
            accuracy_values, grid=grid, spark_width=spark_width,
        ),
    ]
    return "\n".join(line for line in lines if line)


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
        prior = ordered[max(0, i - window + 1):i]
        if not prior:
            return None
        weights = session_recency_weights(len(prior))
        total = sum(weights)
        wpm = sum(compute_wpm(h) * w for h, w in zip(prior, weights, strict=True)) / total
        acc = sum(
            compute_accuracy(h) * 100 * w
            for h, w in zip(prior, weights, strict=True)
        ) / total
        return SessionStatsBaseline(wpm=wpm, accuracy_pct=acc)
    return None


def _format_metric_delta(
    current: float,
    previous: float,
    *,
    higher_is_better: bool = True,
    suffix: str = "",
) -> str:
    delta = current - previous
    if round(abs(delta), 1) == 0:
        return ""
    improved = delta > 0 if higher_is_better else delta < 0
    color = _DELTA_IMPROVE_COLOR if improved else _DELTA_REGRESS_COLOR
    arrow = "↑" if delta > 0 else "↓"
    return f" [{color}]{arrow}{abs(delta):.1f}{suffix}[/]"


def format_session_stats_line(
    result: SessionResult,
    *,
    baseline: SessionStatsBaseline | None = None,
) -> str:
    wpm = compute_wpm(result)
    acc = compute_accuracy(result) * 100
    duration = result.duration_ns / 1e9
    wpm_delta = ""
    acc_delta = ""
    if baseline is not None:
        wpm_delta = _format_metric_delta(wpm, baseline.wpm)
        acc_delta = _format_metric_delta(
            acc, baseline.accuracy_pct, suffix="%",
        )
    return (
        f"Last: WPM [bold]{wpm:5.1f}[/]{wpm_delta}  "
        f"Acc [bold]{acc:5.1f}%[/]{acc_delta}  "
        f"Time [bold]{duration:5.1f}s[/]"
    )
