from keystrike.domain.aggregate import (
    _combine_transition_maps_weighted,
    aggregate_session,
    aggregate_transitions,
    combine,
    combine_sessions,
    combine_transitions,
    merge_key_stats,
    merge_transition_stats,
    per_key_deltas,
    per_transition_deltas,
    session_recency_weights,
    transition_key,
)
from keystrike.domain.confidence import (
    SESSION_RECENCY_DECAY,
    confidence_of,
    transition_accuracy_of,
    transition_confidence_of,
)
from keystrike.domain.enums import Mode
from keystrike.domain.models import Bigram, KeyStats, Keystroke, SessionResult, TransitionStats


def _session(
    session_id: str = "s1",
    started_at: float = 1000.0,
    duration_ns: int = 1_000_000_000,
    layout: str = "qwerty",
) -> SessionResult:
    return SessionResult(
        schema_version=1,
        session_id=session_id,
        started_at=started_at,
        duration_ns=duration_ns,
        layout=layout,
        mode=Mode.ADAPTIVE,
        lesson_alphabet=(),
        focus_key=None,
        total_keystrokes=0,
        correct_keystrokes=0,
    )


def test_aggregate_counts_attempts_per_key():
    keys = [
        Keystroke(codepoint=ord("a"), typed=ord("a"), t_ns=0, correct=True),
        Keystroke(codepoint=ord("a"), typed=ord("x"), t_ns=50_000_000, correct=False),
        Keystroke(codepoint=ord("a"), typed=ord("a"), t_ns=100_000_000, correct=True),
    ]
    stats = aggregate_session(_session(), keys)
    assert stats[ord("a")].attempt_count == 3
    assert stats[ord("a")].samples == 1


def test_aggregate_single_session_mean_time():
    # Type a, a, a with 100ms between each correct one. Mean should be 100ms.
    keys = [
        Keystroke(codepoint=ord("a"), typed=ord("a"), t_ns=0, correct=True),
        Keystroke(codepoint=ord("a"), typed=ord("a"), t_ns=100_000_000, correct=True),
        Keystroke(codepoint=ord("a"), typed=ord("a"), t_ns=200_000_000, correct=True),
    ]
    stats = aggregate_session(_session(), keys)
    ks = stats[ord("a")]
    assert ks.samples == 2  # 3 correct → 2 intervals
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
    assert stats[ord("b")].samples == 0  # no interval measured (single correct)


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
    a = KeyStats(codepoint=ord("x"), samples=2, mean_time_ns=100.0, error_count=1, last_seen=100.0)
    b = KeyStats(codepoint=ord("x"), samples=3, mean_time_ns=200.0, error_count=2, last_seen=200.0)
    m = merge_key_stats(a, b)
    assert m.samples == 5
    # (2*100 + 3*200) / 5 = 160
    assert abs(m.mean_time_ns - 160.0) < 1e-9
    assert m.error_count == 3
    assert m.last_seen == 200.0


def test_combine_multiple_maps():
    a = {ord("x"): KeyStats(ord("x"), 1, 100.0, 0, 1.0)}
    b = {
        ord("x"): KeyStats(ord("x"), 1, 300.0, 1, 2.0),
        ord("y"): KeyStats(ord("y"), 2, 50.0, 0, 3.0),
    }
    out = combine(a, b)
    assert out[ord("x")].samples == 2
    assert abs(out[ord("x")].mean_time_ns - 200.0) < 1e-9
    assert out[ord("y")].samples == 2


def test_session_recency_weights_newest_is_one():
    assert session_recency_weights(1) == [1.0]
    assert session_recency_weights(3) == [
        SESSION_RECENCY_DECAY**2,
        SESSION_RECENCY_DECAY,
        1.0,
    ]


def test_combine_sessions_favors_recent_session():
    s1 = _session("s1", started_at=1.0)
    s2 = _session("s2", started_at=2.0)
    keys1 = [
        Keystroke(codepoint=ord("a"), typed=ord("a"), t_ns=0, correct=True),
        Keystroke(codepoint=ord("a"), typed=ord("a"), t_ns=100_000_000, correct=True),
    ]
    keys2 = [
        Keystroke(codepoint=ord("a"), typed=ord("a"), t_ns=0, correct=True),
        Keystroke(codepoint=ord("a"), typed=ord("a"), t_ns=300_000_000, correct=True),
    ]
    out = combine_sessions([(s1, keys1), (s2, keys2)])
    w_old, w_new = session_recency_weights(2)
    expected = (100_000_000 * w_old + 300_000_000 * w_new) / (w_old + w_new)
    assert abs(out.keys[ord("a")].mean_time_ns - expected) < 1
    assert out.keys[ord("a")].mean_time_ns > 200_000_000


def test_combine_sessions_weights_recent_attempts_more():
    s1 = _session("s1", started_at=1.0)
    s2 = _session("s2", started_at=2.0)
    keys1 = [
        Keystroke(codepoint=ord("a"), typed=ord("a"), t_ns=0, correct=True),
        Keystroke(codepoint=ord("a"), typed=ord("a"), t_ns=100_000_000, correct=True),
    ]
    keys2 = [
        Keystroke(codepoint=ord("a"), typed=ord("a"), t_ns=0, correct=True),
    ]
    out = combine_sessions([(s1, keys1), (s2, keys2)])
    w_old, w_new = session_recency_weights(2)
    expected_attempts = round(2 * w_old + 1 * w_new)
    assert out.keys[ord("a")].attempt_count == expected_attempts
    assert out.keys[ord("a")].attempt_count < 3


def test_combine_sessions_recent_errors_weigh_more_on_confidence():
    s1 = _session("s1", started_at=1.0)
    s2 = _session("s2", started_at=2.0)
    # Old session: fast and clean. Recent session: fast but half wrong.
    keys1 = [
        Keystroke(codepoint=ord("a"), typed=ord("a"), t_ns=0, correct=True),
        Keystroke(codepoint=ord("a"), typed=ord("a"), t_ns=100_000_000, correct=True),
        Keystroke(codepoint=ord("a"), typed=ord("a"), t_ns=200_000_000, correct=True),
    ]
    keys2 = [
        Keystroke(codepoint=ord("a"), typed=ord("a"), t_ns=0, correct=True),
        Keystroke(codepoint=ord("a"), typed=ord("x"), t_ns=50_000_000, correct=False),
        Keystroke(codepoint=ord("a"), typed=ord("a"), t_ns=150_000_000, correct=True),
    ]
    stats = combine_sessions([(s1, keys1), (s2, keys2)]).keys
    equal_weight = combine(
        {ord("a"): aggregate_session(s1, keys1)[ord("a")]},
        {ord("a"): aggregate_session(s2, keys2)[ord("a")]},
    )
    assert confidence_of(ord("a"), stats, target=200.0) < confidence_of(
        ord("a"),
        equal_weight,
        target=200.0,
    )


def test_combine_sessions_includes_transitions_from_iterators():
    keys = iter(
        [
            Keystroke(codepoint=ord("a"), typed=ord("a"), t_ns=0, correct=True),
            Keystroke(codepoint=ord("b"), typed=ord("b"), t_ns=100_000_000, correct=True),
        ]
    )
    out = combine_sessions([(_session(), keys)])
    assert out.keys[ord("b")].samples == 1
    assert out.transitions[Bigram(ord("a"), ord("b"))].samples == 1


def test_per_transition_deltas_tracks_prev_to_next_pair():
    keys = [
        Keystroke(codepoint=ord("a"), typed=ord("a"), t_ns=0, correct=True),
        Keystroke(codepoint=ord("b"), typed=ord("b"), t_ns=100_000_000, correct=True),
        Keystroke(codepoint=ord("c"), typed=ord("c"), t_ns=250_000_000, correct=True),
    ]
    deltas = per_transition_deltas(keys)
    assert deltas[Bigram(ord("a"), ord("b"))] == [100_000_000]
    assert deltas[Bigram(ord("b"), ord("c"))] == [150_000_000]


def test_aggregate_transitions_skips_same_key_pairs():
    keys = [
        Keystroke(codepoint=ord("a"), typed=ord("a"), t_ns=0, correct=True),
        Keystroke(codepoint=ord("a"), typed=ord("a"), t_ns=100_000_000, correct=True),
        Keystroke(codepoint=ord("b"), typed=ord("b"), t_ns=200_000_000, correct=True),
    ]
    transitions = aggregate_transitions(_session(), keys)
    assert Bigram(ord("a"), ord("a")) not in transitions
    assert Bigram(ord("a"), ord("b")) in transitions


def test_per_transition_deltas_skips_same_key_pairs():
    keys = [
        Keystroke(codepoint=ord("a"), typed=ord("a"), t_ns=0, correct=True),
        Keystroke(codepoint=ord("a"), typed=ord("a"), t_ns=100_000_000, correct=True),
        Keystroke(codepoint=ord("b"), typed=ord("b"), t_ns=250_000_000, correct=True),
    ]
    deltas = per_transition_deltas(keys)
    assert Bigram(ord("a"), ord("a")) not in deltas
    assert deltas[Bigram(ord("a"), ord("b"))] == [150_000_000]


def test_aggregate_transitions_attributes_errors_to_pair():
    keys = [
        Keystroke(codepoint=ord("a"), typed=ord("a"), t_ns=0, correct=True),
        Keystroke(codepoint=ord("b"), typed=ord("x"), t_ns=50_000_000, correct=False),
        Keystroke(codepoint=ord("b"), typed=ord("b"), t_ns=100_000_000, correct=True),
    ]
    transitions = aggregate_transitions(_session(), keys)
    ab = transitions[Bigram(ord("a"), ord("b"))]
    assert ab.error_count == 1
    assert ab.samples == 1
    assert abs(ab.mean_time_ns - 100_000_000) < 1


def test_aggregate_transitions_skips_error_on_first_keystroke():
    keys = [
        Keystroke(codepoint=ord("a"), typed=ord("x"), t_ns=0, correct=False),
        Keystroke(codepoint=ord("a"), typed=ord("a"), t_ns=50_000_000, correct=True),
    ]
    transitions = aggregate_transitions(_session(), keys)
    assert Bigram(ord("a"), ord("a")) not in transitions
    assert transitions == {}


def test_merge_transition_stats_weighted_mean():
    a = TransitionStats(ord("a"), ord("b"), 2, 100.0, 1, 100.0)
    b = TransitionStats(ord("a"), ord("b"), 3, 200.0, 2, 200.0)
    merged = merge_transition_stats(a, b)
    assert merged.samples == 5
    assert abs(merged.mean_time_ns - 160.0) < 1e-9
    assert merged.error_count == 3


def test_combine_transitions_multiple_maps():
    ab_key = Bigram(ord("a"), ord("b"))
    bc_key = Bigram(ord("b"), ord("c"))
    a = {ab_key: TransitionStats(ord("a"), ord("b"), 1, 100.0, 0, 1.0)}
    b = {
        ab_key: TransitionStats(ord("a"), ord("b"), 1, 300.0, 1, 2.0),
        bc_key: TransitionStats(ord("b"), ord("c"), 2, 50.0, 0, 3.0),
    }
    out = combine_transitions(a, b)
    assert out[ab_key].samples == 2
    assert abs(out[ab_key].mean_time_ns - 200.0) < 1e-9
    assert out[bc_key].samples == 2


def test_combine_transitions_drops_same_key_pairs():
    stale = {Bigram(ord("a"), ord("a")): TransitionStats(ord("a"), ord("a"), 1, 100.0, 0, 1.0)}
    valid = {Bigram(ord("a"), ord("b")): TransitionStats(ord("a"), ord("b"), 1, 100.0, 0, 1.0)}
    out = combine_transitions(stale, valid)
    assert Bigram(ord("a"), ord("a")) not in out
    assert Bigram(ord("a"), ord("b")) in out


def test_transition_key_format():
    assert transition_key(ord("a"), ord("b")) == "ab"


def test_combine_sessions_keeps_transition_samples_when_weight_rounds_down():
    s1 = _session("s1", started_at=1.0)
    s2 = _session("s2", started_at=2.0)
    s3 = _session("s3", started_at=3.0)
    keys1 = [
        Keystroke(codepoint=ord("e"), typed=ord("e"), t_ns=0, correct=True),
        Keystroke(codepoint=ord("o"), typed=ord("o"), t_ns=196_000_000, correct=True),
    ]
    keys2 = [
        Keystroke(codepoint=ord("e"), typed=ord("e"), t_ns=0, correct=True),
    ]
    keys3 = [
        Keystroke(codepoint=ord("e"), typed=ord("e"), t_ns=0, correct=True),
    ]
    out = combine_sessions([(s1, keys1), (s2, keys2), (s3, keys3)])
    eo = out.transitions[Bigram(ord("e"), ord("o"))]
    assert eo.samples > 0
    assert eo.mean_time_ns > 0
    assert transition_accuracy_of(eo) > 0


def test_weighted_transition_merge_never_zeros_samples_with_mean():
    eo_key = Bigram(ord("e"), ord("o"))
    old = TransitionStats(
        ord("e"),
        ord("o"),
        1,
        196_000_000.0,
        0,
        1.0,
        attempt_count=1,
    )
    recent = TransitionStats(
        ord("e"),
        ord("o"),
        0,
        0.0,
        0,
        2.0,
        attempt_count=0,
    )
    merged = _combine_transition_maps_weighted(
        [{eo_key: old}, {eo_key: recent}],
        session_recency_weights(2),
    )[eo_key]
    assert merged.samples > 0
    assert merged.mean_time_ns > 0
    assert transition_accuracy_of(merged) > 0


def test_weighted_transition_merge_keeps_attempt_count_with_samples():
    """Recency-weighted attempt_count must not round to 0 while samples stay > 0."""
    eo_key = Bigram(ord("e"), ord("o"))
    old = TransitionStats(
        ord("e"),
        ord("o"),
        1,
        196_000_000.0,
        0,
        1.0,
        attempt_count=1,
    )
    recent = TransitionStats(
        ord("e"),
        ord("o"),
        0,
        0.0,
        0,
        2.0,
        attempt_count=0,
    )
    # Oldest session weight 0.49 — round(0.49) would zero attempt_count without bump.
    merged = _combine_transition_maps_weighted(
        [{eo_key: old}, {eo_key: recent}, {eo_key: recent}],
        session_recency_weights(3),
    )[eo_key]
    assert merged.samples > 0
    assert merged.attempt_count > 0
    target = 60_000 / 300  # default 300 cpm
    assert transition_confidence_of(ord("e"), ord("o"), {eo_key: merged}, target) > 0
