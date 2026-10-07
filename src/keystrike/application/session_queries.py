"""Shared session header queries and WPM/accuracy metrics for application use cases."""

from __future__ import annotations

from keystrike.domain.generator import goal_cpm, typical_keystrokes_per_word
from keystrike.domain.models import SessionResult, Settings
from keystrike.domain.protocols import SessionRepository


def _words_for_wpm(result: SessionResult) -> float:
    if result.words_completed > 0:
        return float(result.words_completed)
    if result.correct_keystrokes <= 0:
        return 0.0
    # Legacy sessions without words_completed: estimate from keystrokes
    # (spaces included) under the word bounds the session was typed with.
    return result.correct_keystrokes / typical_keystrokes_per_word(
        generated_min_len=result.generated_min_len,
        generated_max_len=result.generated_max_len,
    )


def compute_wpm(result: SessionResult) -> float:
    """Words per minute from completed lesson words, not chars/5."""
    if result.wpm > 0:
        return result.wpm
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


# Fewer whole words than this (a no-space drill, a cut-short lesson) give a
# skewed keystrokes-per-word, so such sessions don't count toward the rate.
MIN_RATE_WORDS = 5


def _counts_toward_rate(h: SessionResult) -> bool:
    return h.cpm > 0 and h.wpm > 0 and h.words_completed >= MIN_RATE_WORDS


def keystrokes_per_word(
    repo: SessionRepository, settings: Settings, layout: str | None = None
) -> float:
    """Measured keystrokes per word (spaces included): total CPM / total WPM
    over the last ``confidence_session_window`` sessions of ``layout``
    (default ``settings.layout``) that saved both and completed at least
    ``MIN_RATE_WORDS`` words. Falls back to the word-length midpoint + 1."""
    measured = sorted(
        (h for h in repo.iter_headers(layout or settings.layout) if _counts_toward_rate(h)),
        key=lambda h: h.started_at,
    )[-settings.confidence_session_window :]
    if measured:
        return sum(h.cpm for h in measured) / sum(h.wpm for h in measured)
    return typical_keystrokes_per_word(
        generated_min_len=settings.word_gen.min_len,
        generated_max_len=settings.word_gen.max_len,
    )


def target_speed_cpm(repo: SessionRepository, settings: Settings, layout: str | None = None) -> int:
    """The speed goal in CPM for ``layout`` (default ``settings.layout``; see `goal_cpm`)."""
    return goal_cpm(settings, keystrokes_per_word(repo, settings, layout))
