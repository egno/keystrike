from keystrike.domain.confidence import (
    compute_unlocked,
    confidence_of,
    key_confidence,
    select_focus,
    target_ms_per_char,
)
from keystrike.domain.models import KeyStats


def test_target_ms_per_char():
    assert target_ms_per_char(300) == 200.0


def test_key_confidence_at_target_speed_is_one():
    assert key_confidence(200.0, 200_000_000.0) == 1.0


def test_key_confidence_faster_than_target_is_above_one():
    assert key_confidence(200.0, 100_000_000.0) == 2.0


def test_key_confidence_slower_than_target_is_below_one():
    assert key_confidence(200.0, 400_000_000.0) == 0.5


def test_key_confidence_no_samples_is_zero():
    assert key_confidence(200.0, 0.0) == 0.0


def _stats(codepoint: int, mean_time_ns: float, peak_confidence: float) -> KeyStats:
    return KeyStats(
        codepoint=codepoint,
        samples=10,
        mean_time_ns=mean_time_ns,
        error_count=0,
        last_seen=0.0,
        peak_confidence=peak_confidence,
    )


def test_confidence_of_unseen_key_is_zero():
    assert confidence_of(ord("a"), {}, target=200.0, recover_keys=False) == 0.0


def test_confidence_of_live_uses_mean_time():
    stats = {ord("a"): _stats(ord("a"), mean_time_ns=200_000_000.0, peak_confidence=5.0)}
    assert confidence_of(ord("a"), stats, target=200.0, recover_keys=False) == 1.0


def test_confidence_of_recover_uses_peak():
    stats = {ord("a"): _stats(ord("a"), mean_time_ns=400_000_000.0, peak_confidence=1.5)}
    assert confidence_of(ord("a"), stats, target=200.0, recover_keys=True) == 1.5


def test_compute_unlocked_force_includes_alphabet_fraction():
    learn_order = tuple(range(10))
    unlocked = compute_unlocked(learn_order, alphabet_size=0.3, stats={}, target=200.0,
                                 recover_keys=False)
    assert unlocked == learn_order[:3]


def test_compute_unlocked_advances_when_threshold_met():
    learn_order = (1, 2, 3, 4)
    stats = {1: _stats(1, mean_time_ns=100_000_000.0, peak_confidence=0.0)}  # confidence 2.0
    unlocked = compute_unlocked(learn_order, alphabet_size=0.25, stats=stats, target=200.0,
                                 recover_keys=False)
    assert unlocked == (1, 2)


def test_compute_unlocked_stalls_when_threshold_not_met():
    learn_order = (1, 2, 3, 4)
    stats = {1: _stats(1, mean_time_ns=400_000_000.0, peak_confidence=0.0)}  # confidence 0.5
    unlocked = compute_unlocked(learn_order, alphabet_size=0.25, stats=stats, target=200.0,
                                 recover_keys=False)
    assert unlocked == (1,)


def test_select_focus_picks_weakest_unlocked_key():
    stats = {
        1: _stats(1, mean_time_ns=100_000_000.0, peak_confidence=0.0),  # confidence 2.0
        2: _stats(2, mean_time_ns=400_000_000.0, peak_confidence=0.0),  # confidence 0.5
    }
    assert select_focus((1, 2), stats, target=200.0, recover_keys=False) == 2


def test_select_focus_prefers_never_practiced_key():
    stats = {1: _stats(1, mean_time_ns=100_000_000.0, peak_confidence=0.0)}
    assert select_focus((1, 2), stats, target=200.0, recover_keys=False) == 2
