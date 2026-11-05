"""Small builders for v2 advice in tests."""

from __future__ import annotations

from keystrike.domain.advice import (
    Evidence,
    Kind,
    LessonAdvice,
    Reason,
    Recommendation,
)


def rec(
    kind: Kind,
    *keys: int,
    reason: Reason | None = None,
    strength: float = 1.0,
    events: int = 5,
    opportunities: int = 50,
    applied: float | None = None,
    event_sessions: int | None = None,
) -> Recommendation:
    """A recommendation with enough evidence by default. `applied` defaults
    to what `validate_advice` would set, so tests can skip validation. A
    CONTRAST has its events in 3 sessions by default (it needs 2)."""
    if reason is None:
        reason = {
            Kind.EASE: Reason.MASTERED,
            Kind.CONTRAST: Reason.CONFUSION,
        }.get(kind, Reason.ACCURACY)
    if event_sessions is None and kind is Kind.CONTRAST:
        event_sessions = 3
    full = strength * min(1.0, events / 5)
    return Recommendation(
        kind=kind,
        keys=keys,
        reason=reason,
        strength=strength,
        evidence=Evidence(events, opportunities, 3, event_sessions),
        applied=full if applied is None else applied,
    )


def advice(*recs: Recommendation, source: str = "", summary: str = "") -> LessonAdvice:
    return LessonAdvice(source=source, summary=summary, recommendations=recs)
