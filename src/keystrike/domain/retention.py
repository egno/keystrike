"""Pure retention rule for per-session stats.

Only a trailing window of sessions per layout is ever replayed: `combine_sessions`
reads the last `confidence_session_window` sessions, and the per-session trend
lines replay that window once for each of the last `window` sessions — so the
oldest session whose tallies can still matter is `2 * window - 1` back. Every
session older than that keeps its history row (WPM, accuracy, snapshots) but
drops its `SessionStats`.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace

from .models import SessionResult, SessionStats

_EMPTY_STATS = SessionStats()


def stats_retention_count(window: int) -> int:
    """How many newest sessions per layout must keep their `SessionStats`."""
    return max(1, 2 * window - 1)


def prune_session_stats(
    headers: Iterable[SessionResult],
    *,
    window: int,
) -> tuple[list[SessionResult], int]:
    """Drop stats from every session outside its layout's retention window.

    Returns the headers in their original order with the affected ones
    replaced, plus how many were changed (0 means nothing needs rewriting).
    """
    ordered = list(headers)
    keep = stats_retention_count(window)

    by_layout: dict[str, list[int]] = {}
    for i, header in enumerate(ordered):
        by_layout.setdefault(header.layout, []).append(i)

    changed = 0
    for indices in by_layout.values():
        newest_first = sorted(indices, key=lambda i: ordered[i].started_at, reverse=True)
        for i in newest_first[keep:]:
            if ordered[i].stats.is_empty:
                continue
            ordered[i] = replace(ordered[i], stats=_EMPTY_STATS)
            changed += 1
    return ordered, changed
