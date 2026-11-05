"""The public facade for advisor plugins. A plugin imports from here and
from nowhere else in `keystrike` (docs/ADVISOR-PLUGINS.md §5).

Change `PLUGIN_API_VERSION` (in `keystrike.domain.advice`) on any change
that breaks plugins."""

from __future__ import annotations

from typing import Protocol

from keystrike.application.advisor_registry import AdvisorRegistry
from keystrike.domain.advice import (
    CONTRAST_MIN_EVENT_SESSIONS,
    CONTRAST_MIN_EVENTS,
    DEFAULT_RECENCY_DECAY,
    EMPTY_ADVICE,
    MIN_EVENTS,
    MIN_OPPORTUNITIES,
    ON_TRACK,
    PLUGIN_API_VERSION,
    AdviceDigest,
    Advisor,
    AdvisorCapabilities,
    AdvisorContext,
    AdvisorSpec,
    CourseState,
    Coverage,
    Evidence,
    KeyTiming,
    Kind,
    LessonAdvice,
    Reason,
    RecentTally,
    Recommendation,
    SettingField,
    Tally,
    effective_strength,
    error_rate_ranked,
    format_char,
    neighbors,
    render_summary,
)
from keystrike.domain.enums import Finger, Hand
from keystrike.domain.keystroke_insights import (
    Confusion,
    FingerErrors,
    KeystrokeInsights,
)
from keystrike.domain.models import Bigram, KeyPos, Keystroke, KeyTally, SessionResult
from keystrike.domain.timing import (
    MIN_INTERVAL_MS,
    TAIL_FACTOR,
    eligible_intervals,
    key_timings,
    weighted_median,
)


class PluginModule(Protocol):
    API_VERSION: int

    def register(self, registry: AdvisorRegistry) -> None: ...


__all__ = [
    "CONTRAST_MIN_EVENTS",
    "CONTRAST_MIN_EVENT_SESSIONS",
    "DEFAULT_RECENCY_DECAY",
    "EMPTY_ADVICE",
    "MIN_EVENTS",
    "MIN_INTERVAL_MS",
    "MIN_OPPORTUNITIES",
    "ON_TRACK",
    "PLUGIN_API_VERSION",
    "TAIL_FACTOR",
    "AdviceDigest",
    "Advisor",
    "AdvisorCapabilities",
    "AdvisorContext",
    "AdvisorRegistry",
    "AdvisorSpec",
    "Bigram",
    "Confusion",
    "CourseState",
    "Coverage",
    "Evidence",
    "Finger",
    "FingerErrors",
    "Hand",
    "KeyPos",
    "KeyTally",
    "KeyTiming",
    "Keystroke",
    "KeystrokeInsights",
    "Kind",
    "LessonAdvice",
    "PluginModule",
    "Reason",
    "RecentTally",
    "Recommendation",
    "SessionResult",
    "SettingField",
    "Tally",
    "effective_strength",
    "eligible_intervals",
    "error_rate_ranked",
    "format_char",
    "key_timings",
    "neighbors",
    "render_summary",
    "weighted_median",
]
