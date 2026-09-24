from dataclasses import replace

from keystrike.domain.enums import Mode
from keystrike.domain.models import KeyTally, SessionResult, SessionStats
from keystrike.domain.retention import prune_session_stats, stats_retention_count


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
