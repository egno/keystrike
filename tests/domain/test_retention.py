import datetime as dt
from dataclasses import replace

from keystrike.domain.enums import Mode
from keystrike.domain.models import KeyTally, SessionResult, SessionStats
from keystrike.domain.retention import (
    HISTORY_MIN_SESSIONS,
    history_retention_count,
    prune_session_history,
    prune_session_stats,
    retained_session_ids,
    stats_retention_count,
)


def _stats() -> SessionStats:
    return SessionStats(keys={ord("a"): KeyTally(1, 100_000_000, 0, 1)})


def _header(session_id: str, started_at: float, layout: str = "qwerty") -> SessionResult:
    return SessionResult(
        schema_version=5,
        session_id=session_id,
        started_at=started_at,
        duration_ns=1_000_000_000,
        layout=layout,
        mode=Mode.ADAPTIVE,
        lesson_alphabet=(ord("a"),),
        focus_key=None,
        total_keystrokes=1,
        correct_keystrokes=1,
        stats=_stats(),
    )


def test_retention_covers_every_session_the_trend_replay_can_reach():
    # Trends replay a `window`-long window once for each of the last `window`
    # sessions, so the oldest session they read is 2*window-1 back.
    assert stats_retention_count(10) == 19
    assert stats_retention_count(1) == 1
    assert stats_retention_count(0) == 1


def test_prune_drops_stats_only_outside_per_layout_window():
    headers = [_header(f"q{i}", started_at=float(i)) for i in range(5)]
    headers.append(_header("d0", started_at=100.0, layout="dvorak"))

    pruned, changed = prune_session_stats(headers, window=2)  # keep 3 per layout

    assert changed == 2
    by_id = {h.session_id: h for h in pruned}
    assert by_id["q0"].stats.is_empty
    assert by_id["q1"].stats.is_empty
    assert not by_id["q2"].stats.is_empty
    assert not by_id["q4"].stats.is_empty
    assert not by_id["d0"].stats.is_empty


def test_prune_keeps_order_and_every_other_field():
    headers = [_header(f"q{i}", started_at=float(i)) for i in range(3)]
    pruned, changed = prune_session_stats(headers, window=1)

    assert changed == 2
    assert [h.session_id for h in pruned] == ["q0", "q1", "q2"]
    assert pruned[0] == replace(headers[0], stats=SessionStats())


def test_prune_uses_started_at_not_list_order():
    newest_first = [_header("new", started_at=9.0), _header("old", started_at=1.0)]
    pruned, changed = prune_session_stats(newest_first, window=1)

    assert changed == 1
    assert not pruned[0].stats.is_empty
    assert pruned[1].stats.is_empty


def test_prune_reports_zero_when_already_pruned():
    headers = [_header("q0", started_at=0.0), _header("q1", started_at=1.0)]
    once, changed_once = prune_session_stats(headers, window=1)
    again, changed_again = prune_session_stats(once, window=1)

    assert changed_once == 1
    assert changed_again == 0
    assert again == once


# 2023-11-14 UTC: a past day for every "old" row below.
_OLD = 1_700_000_000.0
_TODAY = dt.date(2026, 10, 8)
_TODAY_START = dt.datetime(2026, 10, 8, tzinfo=dt.UTC).timestamp()


def _kept(headers: list[SessionResult], window: int = 1) -> set[str]:
    return retained_session_ids(headers, window=window, today=_TODAY, tz=dt.UTC)


def test_history_count_is_twenty_or_the_stats_window():
    assert history_retention_count(10) == HISTORY_MIN_SESSIONS == 20
    assert history_retention_count(15) == stats_retention_count(15) == 29


def test_history_keeps_newest_rows_per_layout():
    headers = [_header(f"q{i}", started_at=_OLD + i) for i in range(25)]
    headers += [_header(f"d{i}", started_at=_OLD + i, layout="dvorak") for i in range(3)]

    kept = _kept(headers)

    assert kept == {f"q{i}" for i in range(5, 25)} | {"d0", "d1", "d2"}


def test_history_keeps_every_row_from_today():
    headers = [_header(f"t{i}", started_at=_TODAY_START + i) for i in range(25)]
    headers.append(_header("old", started_at=_OLD))

    assert _kept(headers) == {f"t{i}" for i in range(25)}


def test_history_today_uses_the_given_time_zone():
    # 23:30 UTC on the day before is already "today" at UTC+1.
    late = _header("late", started_at=_TODAY_START - 1800)
    headers = [late] + [_header(f"t{i}", started_at=_TODAY_START + i) for i in range(20)]
    plus_one = dt.timezone(dt.timedelta(hours=1))

    assert "late" not in _kept(headers)
    assert "late" in retained_session_ids(headers, window=1, today=_TODAY, tz=plus_one)


def test_history_union_does_not_bring_pruned_rows_back():
    # Device A pruned its history; device B still has the old rows. The
    # union, pruned again, drops the same rows A dropped.
    a = [_header(f"q{i}", started_at=_OLD + i) for i in range(25)]
    dropped_by_a = {h.session_id for h in a} - _kept(a)
    b = a[:10] + [_header(f"n{i}", started_at=_OLD + 100 + i) for i in range(3)]

    assert not dropped_by_a & _kept(a + b[10:])


def test_prune_history_deletes_rows_then_stats():
    headers = [_header(f"q{i}", started_at=_OLD + i) for i in range(22)]

    pruned, changed = prune_session_history(headers, window=2, today=_TODAY, tz=dt.UTC)

    assert [h.session_id for h in pruned] == [f"q{i}" for i in range(2, 22)]
    # 2 rows deleted; of the 20 kept, all but the newest 3 drop their stats.
    assert changed == 2 + 17
    assert [h.stats.is_empty for h in pruned] == [True] * 17 + [False] * 3

    again, changed_again = prune_session_history(pruned, window=2, today=_TODAY, tz=dt.UTC)
    assert changed_again == 0
    assert again == pruned
