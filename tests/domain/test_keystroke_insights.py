from __future__ import annotations

import pytest

from keystrike.domain.enums import Finger, Hand
from keystrike.domain.keystroke_insights import (
    Confusion,
    FingerErrors,
    keystroke_insights,
)
from keystrike.domain.models import Keystroke

A, S, D, G, OH = (ord(c) for c in "asdgo")


def _ks(target: int, typed: int, finger: Finger | None = Finger.RING) -> Keystroke:
    return Keystroke(target, typed, 0, correct=target == typed, finger=finger, hand=Hand.L)


def test_repeated_mistypes_are_reported_most_common_first():
    # each stumble is a wrong key, then the retry that gets it right
    stumble_sd = [_ks(S, D), _ks(S, S)]
    stumble_as = [_ks(A, S), _ks(A, A)]
    stumble_ad = [_ks(A, D), _ks(A, A)]
    stream = stumble_sd * 3 + stumble_as * 2 + stumble_ad
    insights = keystroke_insights([stream])
    assert insights.confusions == (Confusion(S, D, 3), Confusion(A, S, 2))  # a->d once: dropped


def test_retries_at_one_position_count_once():
    """The cursor stays on the target after an error, so one stumble of three
    wrong keys is one error, one confusion (the first wrong key), one attempt."""
    stream = [_ks(S, G), _ks(S, D), _ks(S, OH), _ks(S, S)]
    insights = keystroke_insights([stream], min_confusion_count=1)
    assert insights.confusions == (Confusion(S, G, 1),)
    (finger,) = insights.fingers
    assert (finger.errors, finger.attempts) == (1, 1)


def test_a_real_double_letter_is_two_positions():
    insights = keystroke_insights([[_ks(S, S), _ks(S, S)]])
    (finger,) = insights.fingers
    assert (finger.errors, finger.attempts) == (0, 2)


def test_a_wrong_press_after_a_correct_one_on_the_same_key_is_a_new_position():
    insights = keystroke_insights([[_ks(S, S), _ks(S, D)]], min_confusion_count=1)
    assert insights.confusions == (Confusion(S, D, 1),)
    (finger,) = insights.fingers
    assert (finger.errors, finger.attempts) == (1, 2)


def test_finger_error_rates_and_key_filter():
    stream = [_ks(S, D), _ks(S, S), _ks(S, S), _ks(A, A, Finger.PINKY), _ks(ord(" "), A)]
    insights = keystroke_insights([stream], keys=frozenset({A, S}))
    rates = {(f.hand, f.finger): (f.errors, f.attempts) for f in insights.fingers}
    # the retry after the first error is not an attempt; the later correct S is
    assert rates == {(Hand.L, Finger.RING): (1, 2), (Hand.L, Finger.PINKY): (0, 1)}
    assert insights.fingers[0].finger is Finger.RING  # worst first


def test_retries_do_not_leak_across_streams():
    wrong = [_ks(S, D)]
    insights = keystroke_insights([wrong, [_ks(S, S)]])
    (finger,) = insights.fingers
    assert (finger.errors, finger.attempts) == (1, 2)


def test_empty_input():
    assert keystroke_insights([]).is_empty


def test_weights_add_recent_counts_next_to_the_exact_ones():
    old = [_ks(S, D), _ks(S, S)] * 2  # two mistypes in the older session
    new = [_ks(S, D), _ks(S, S)]  # one in the newer session
    insights = keystroke_insights([new, old], weights=[1.0, 0.25], min_confusion_count=1)
    (confusion,) = insights.confusions
    assert confusion.count == 3  # exact: the evidence
    assert confusion.recent_count == 1.0 + 0.25 * 2
    assert confusion.recency == (1.0 + 0.5) / 3
    (finger,) = insights.fingers
    assert (finger.errors, finger.attempts) == (3, 3)
    assert finger.recent_errors == 1.5
    assert finger.recent_attempts == 1.5
    assert finger.recent_error_rate == 1.0


def test_a_mistype_that_is_only_old_has_a_low_recency():
    old = [_ks(S, D), _ks(S, S)] * 3
    insights = keystroke_insights([old], weights=[0.2], min_confusion_count=1)
    assert insights.confusions[0].recency == pytest.approx(0.2)


def test_without_weights_everything_is_recent():
    insights = keystroke_insights([[_ks(S, D), _ks(S, S)] * 2])
    assert insights.confusions[0].recency == 1.0
    assert insights.fingers[0].recent_error_rate == insights.fingers[0].error_rate


def test_unknown_recency_means_full_recency_and_the_plain_rate():
    assert Confusion(S, D, 3).recency == 1.0
    finger = FingerErrors(Hand.L, Finger.RING, errors=1, attempts=4)
    assert finger.recent_error_rate == 0.25


def test_weights_must_match_the_streams():
    with pytest.raises(ValueError, match="argument"):
        keystroke_insights([[_ks(S, S)], [_ks(S, S)]], weights=[1.0])


def test_a_confusion_knows_its_sessions_and_its_events_in_the_newer_half():
    """Streams are newest first. With 5 streams the newer half is the first 3."""
    slip = [_ks(S, D), _ks(S, S)]
    streams = [slip, [], slip * 2, slip, slip]
    (confusion,) = keystroke_insights(streams).confusions
    assert confusion.count == 5
    assert confusion.sessions == 4  # the empty stream has none
    assert confusion.newest_half == 3  # 1 in the newest stream, 2 in the third


def test_old_confusions_have_no_events_in_the_newer_half():
    slip = [_ks(S, D), _ks(S, S)]
    (confusion,) = keystroke_insights([[], [], slip, slip]).confusions
    assert (confusion.sessions, confusion.newest_half) == (2, 0)


def test_one_stream_is_its_own_newer_half():
    slip = [_ks(S, D), _ks(S, S)]
    (confusion,) = keystroke_insights([slip * 2]).confusions
    assert (confusion.sessions, confusion.newest_half) == (1, 2)
