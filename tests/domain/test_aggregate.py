from keystrike.domain.aggregate import (
    aggregate_session,
    aggregate_transitions,
    combine,
    combine_transitions,
    merge_key_stats,
    merge_transition_stats,
    per_key_deltas,
    per_transition_deltas,
    transition_key,
)
from keystrike.domain.enums import Mode
from keystrike.domain.models import KeyStats, Keystroke, SessionResult, TransitionStats


def _session(session_id: str = "s1", started_at: float = 1000.0,
             duration_ns: int = 1_000_000_000, layout: str = "qwerty") -> SessionResult:
    return SessionResult(
        schema_version=1,
        session_id=session_id,
        started_at=started_at,
        duration_ns=duration_ns,
        layout=layout,
        mode=Mode.FREE,
        lesson_alphabet=(),
        focus_key=None,
        total_keystrokes=0,
        correct_keystrokes=0,
    )


def test_aggregate_single_session_mean_time():
    # Type a, a, a with 100ms between each correct one. Mean should be 100ms.
    keys = [
        Keystroke(codepoint=ord("a"), typed=ord("a"), t_ns=0, correct=True),
        Keystroke(codepoint=ord("a"), typed=ord("a"), t_ns=100_000_000, correct=True),
        Keystroke(codepoint=ord("a"), typed=ord("a"), t_ns=200_000_000, correct=True),
    ]
    stats = aggregate_session(_session(), keys)
    ks = stats[ord("a")]
    assert ks.samples == 2                    # 3 correct → 2 intervals
    assert abs(ks.mean_time_ns - 100_000_000) < 1
    assert ks.error_count == 0


def test_aggregate_counts_errors_per_target():
    # Target 'b' but type 'x' twice, then correct.
    keys = [
        Keystroke(codepoint=ord("b"), typed=ord("x"), t_ns=0, correct=False),
        Keystroke(codepoint=ord("b"), typed=ord("x"), t_ns=50_000_000, correct=False),
        Keystroke(codepoint=ord("b"), typed=ord("b"), t_ns=100_000_000, correct=True),
    ]
    stats = aggregate_session(_session(), keys)
    assert stats[ord("b")].error_count == 2
    assert stats[ord("b")].samples == 0       # no interval measured (single correct)


def test_aggregate_last_seen_matches_session_end():
    keys = [Keystroke(codepoint=ord("a"), typed=ord("a"), t_ns=0, correct=True)]
    s = _session(started_at=1000.0, duration_ns=5_000_000_000)
    stats = aggregate_session(s, keys)
    assert stats[ord("a")].last_seen == 1005.0


def test_per_key_deltas_chronological_order():
    keys = [
        Keystroke(codepoint=ord("a"), typed=ord("a"), t_ns=0, correct=True),
        Keystroke(codepoint=ord("a"), typed=ord("a"), t_ns=100_000_000, correct=True),
        Keystroke(codepoint=ord("a"), typed=ord("a"), t_ns=250_000_000, correct=True),
    ]
    deltas = per_key_deltas(keys)
    assert deltas[ord("a")] == [100_000_000, 150_000_000]


def test_per_key_deltas_ignores_wrong_keystrokes():
    keys = [
        Keystroke(codepoint=ord("a"), typed=ord("a"), t_ns=0, correct=True),
        Keystroke(codepoint=ord("a"), typed=ord("x"), t_ns=50_000_000, correct=False),
        Keystroke(codepoint=ord("a"), typed=ord("a"), t_ns=200_000_000, correct=True),
    ]
    deltas = per_key_deltas(keys)
    # The wrong keystroke doesn't reset the "last correct" baseline.
    assert deltas[ord("a")] == [200_000_000]


def test_per_key_deltas_separates_by_codepoint():
    # Delta is always "time since the immediately preceding correct keystroke,
    # regardless of which key that was" — bucketed by the *current* codepoint.
    keys = [
        Keystroke(codepoint=ord("a"), typed=ord("a"), t_ns=0, correct=True),
        Keystroke(codepoint=ord("b"), typed=ord("b"), t_ns=50_000_000, correct=True),
        Keystroke(codepoint=ord("a"), typed=ord("a"), t_ns=150_000_000, correct=True),
    ]
    deltas = per_key_deltas(keys)
    assert deltas[ord("a")] == [100_000_000]
    assert deltas[ord("b")] == [50_000_000]


def test_merge_weighted_mean():
    a = KeyStats(codepoint=ord("x"), samples=2, mean_time_ns=100.0,
                 error_count=1, last_seen=100.0)
    b = KeyStats(codepoint=ord("x"), samples=3, mean_time_ns=200.0,
                 error_count=2, last_seen=200.0)
    m = merge_key_stats(a, b)
    assert m.samples == 5
    # (2*100 + 3*200) / 5 = 160
    assert abs(m.mean_time_ns - 160.0) < 1e-9
    assert m.error_count == 3
    assert m.last_seen == 200.0


def test_combine_multiple_maps():
    a = {ord("x"): KeyStats(ord("x"), 1, 100.0, 0, 1.0)}
    b = {ord("x"): KeyStats(ord("x"), 1, 300.0, 1, 2.0),
         ord("y"): KeyStats(ord("y"), 2, 50.0, 0, 3.0)}
    out = combine(a, b)
    assert out[ord("x")].samples == 2
    assert abs(out[ord("x")].mean_time_ns - 200.0) < 1e-9
    assert out[ord("y")].samples == 2


def test_per_transition_deltas_tracks_prev_to_next_pair():
    keys = [
        Keystroke(codepoint=ord("a"), typed=ord("a"), t_ns=0, correct=True),
        Keystroke(codepoint=ord("b"), typed=ord("b"), t_ns=100_000_000, correct=True),
        Keystroke(codepoint=ord("c"), typed=ord("c"), t_ns=250_000_000, correct=True),
    ]
    deltas = per_transition_deltas(keys)
    assert deltas["ab"] == [100_000_000]
    assert deltas["bc"] == [150_000_000]


def test_aggregate_transitions_attributes_errors_to_pair():
    keys = [
        Keystroke(codepoint=ord("a"), typed=ord("a"), t_ns=0, correct=True),
        Keystroke(codepoint=ord("b"), typed=ord("x"), t_ns=50_000_000, correct=False),
        Keystroke(codepoint=ord("b"), typed=ord("b"), t_ns=100_000_000, correct=True),
    ]
    transitions = aggregate_transitions(_session(), keys)
    ab = transitions["ab"]
    assert ab.error_count == 1
    assert ab.samples == 1
    assert abs(ab.mean_time_ns - 100_000_000) < 1


def test_aggregate_transitions_skips_error_on_first_keystroke():
    keys = [
        Keystroke(codepoint=ord("a"), typed=ord("x"), t_ns=0, correct=False),
        Keystroke(codepoint=ord("a"), typed=ord("a"), t_ns=50_000_000, correct=True),
    ]
    transitions = aggregate_transitions(_session(), keys)
    assert "aa" not in transitions
    assert transitions == {}


def test_merge_transition_stats_weighted_mean():
    a = TransitionStats(ord("a"), ord("b"), 2, 100.0, 1, 100.0)
    b = TransitionStats(ord("a"), ord("b"), 3, 200.0, 2, 200.0)
    merged = merge_transition_stats(a, b)
    assert merged.samples == 5
    assert abs(merged.mean_time_ns - 160.0) < 1e-9
    assert merged.error_count == 3


def test_combine_transitions_multiple_maps():
    a = {"ab": TransitionStats(ord("a"), ord("b"), 1, 100.0, 0, 1.0)}
    b = {
        "ab": TransitionStats(ord("a"), ord("b"), 1, 300.0, 1, 2.0),
        "bc": TransitionStats(ord("b"), ord("c"), 2, 50.0, 0, 3.0),
    }
    out = combine_transitions(a, b)
    assert out["ab"].samples == 2
    assert abs(out["ab"].mean_time_ns - 200.0) < 1e-9
    assert out["bc"].samples == 2


def test_transition_key_format():
    assert transition_key(ord("a"), ord("b")) == "ab"
