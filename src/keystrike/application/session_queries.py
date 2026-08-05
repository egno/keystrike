"""Shared session header queries and WPM/accuracy metrics for application use cases."""

from __future__ import annotations

from keystrike.domain.generator import typical_chars_per_word, wpm_from_cpm
from keystrike.domain.models import SessionResult
from keystrike.domain.protocols import SessionRepository


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


def latest_session_header(repo: SessionRepository, layout: str) -> SessionResult | None:
    """Most recently finished session for ``layout``, if any — the header
    `BuildLesson` reads to decide whether the next lesson needs the
    lesson-WPM remedial-focus gate (`session_wpm_below_target`)."""
    headers = list(repo.iter_headers(layout))
    return max(headers, key=lambda h: h.started_at, default=None)


def session_wpm_below_target(
    result: SessionResult,
    *,
    generated_min_len: int | None = None,
    generated_max_len: int | None = None,
) -> bool:
    """Whether a finished session's own WPM fell short of its own target
    speed. Drives `BuildLesson`'s remedial lesson-alphabet focus gate;
    legacy sessions with no recorded target (``target_speed_cpm == 0``)
    never trigger it. Word-length bounds come from the session header
    (snapshotted at finish); optional overrides exist for tests."""
    if result.target_speed_cpm <= 0 or result.words_completed <= 0:
        return False
    min_len = generated_min_len if generated_min_len is not None else result.generated_min_len
    max_len = generated_max_len if generated_max_len is not None else result.generated_max_len
    target_wpm = wpm_from_cpm(
        result.target_speed_cpm,
        generated_min_len=min_len,
        generated_max_len=max_len,
    )
    return compute_wpm(result) < target_wpm
