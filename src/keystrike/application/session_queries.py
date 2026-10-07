"""Shared session header queries and WPM/accuracy metrics for application use cases."""

from __future__ import annotations

from keystrike.domain.generator import typical_chars_per_word
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
    `BuildLesson` reads to keep the last lesson's focus."""
    headers = list(repo.iter_headers(layout))
    return max(headers, key=lambda h: h.started_at, default=None)
