"""Pure retention rules for session history rows and per-session stats.

History rows: per layout, the newest `history_retention_count(window)` rows
stay, plus every row from the current local day (the daily learn budget sums
them). Older rows are deleted. The rule is monotone — a row outside the newest
N of a set is outside the newest N of every superset, and a past day never
becomes today again — so git sync can union two indexes and prune the result
without bringing deleted rows back.

Stats: only a trailing window of sessions per layout is ever replayed:
`combine_sessions` reads the last `confidence_session_window` sessions, and the
per-session trend lines replay that window once for each of the last `window`
sessions — so the oldest session whose tallies can still matter is
`2 * window - 1` back. A kept row older than that keeps its header (WPM,
accuracy, snapshots) but drops its `SessionStats`.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable
from dataclasses import replace
from typing import Protocol

from .daily_learn import session_local_date
from .models import SessionResult, SessionStats

_EMPTY_STATS = SessionStats()

# History rows kept per layout, at minimum (the history view shows 20).
HISTORY_MIN_SESSIONS = 20


class DatedSession(Protocol):
    """What the history rule reads from a row: a `SessionResult` or a sync
    `SessionIndexEntry`."""

    @property
    def session_id(self) -> str: ...
    @property
    def layout(self) -> str: ...
    @property
    def started_at(self) -> float: ...


def stats_retention_count(window: int) -> int:
    """How many newest sessions per layout must keep their `SessionStats`."""
    return max(1, 2 * window - 1)


def history_retention_count(window: int) -> int:
    """How many newest history rows per layout always stay. Never fewer than
    the rows that keep their stats, so the trend replay still finds them."""
    return max(HISTORY_MIN_SESSIONS, stats_retention_count(window))


def retained_session_ids(
    rows: Iterable[DatedSession],
    *,
    window: int,
    today: dt.date,
    tz: dt.tzinfo,
) -> set[str]:
    """Ids of the rows the history rule keeps: per layout, the newest
    `history_retention_count(window)` rows plus every row dated `today` or
    later (in `tz`; later covers a device with a clock ahead)."""
    keep = history_retention_count(window)
    by_layout: dict[str, list[DatedSession]] = {}
    for row in rows:
        by_layout.setdefault(row.layout, []).append(row)

    kept: set[str] = set()
    for layout_rows in by_layout.values():
        newest_first = sorted(layout_rows, key=lambda r: r.started_at, reverse=True)
        kept.update(r.session_id for r in newest_first[:keep])
        kept.update(
            r.session_id
            for r in newest_first[keep:]
            if session_local_date(r.started_at, tz) >= today
        )
    return kept


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


def prune_session_history(
    headers: Iterable[SessionResult],
    *,
    window: int,
    today: dt.date,
    tz: dt.tzinfo,
) -> tuple[list[SessionResult], int]:
    """Delete rows outside the history rule, then drop stats outside the
    stats window. Returns the kept headers in their original order plus how
    many rows were deleted or changed (0 means nothing needs rewriting)."""
    ordered = list(headers)
    kept_ids = retained_session_ids(ordered, window=window, today=today, tz=tz)
    kept = [h for h in ordered if h.session_id in kept_ids]
    pruned, stats_changed = prune_session_stats(kept, window=window)
    return pruned, len(ordered) - len(kept) + stats_changed
