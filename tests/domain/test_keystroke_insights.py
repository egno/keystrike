from __future__ import annotations

from keystrike.domain.enums import Finger, Hand
from keystrike.domain.keystroke_insights import Confusion, keystroke_insights
from keystrike.domain.models import Keystroke

A, S, D = ord("a"), ord("s"), ord("d")


def _ks(target: int, typed: int, finger: Finger | None = Finger.RING) -> Keystroke:
    return Keystroke(target, typed, 0, correct=target == typed, finger=finger, hand=Hand.L)


def test_repeated_mistypes_are_reported_most_common_first():
    stream = [_ks(S, D), _ks(S, D), _ks(S, D), _ks(A, S), _ks(A, S), _ks(A, D)]
    insights = keystroke_insights([stream])
    assert insights.confusions == (Confusion(S, D, 3), Confusion(A, S, 2))  # a->d once: dropped


def test_finger_error_rates_and_key_filter():
    stream = [_ks(S, D), _ks(S, S), _ks(A, A, Finger.PINKY), _ks(ord(" "), A)]
    insights = keystroke_insights([stream], keys=frozenset({A, S}))
    rates = {(f.hand, f.finger): (f.errors, f.attempts) for f in insights.fingers}
    assert rates == {(Hand.L, Finger.RING): (1, 2), (Hand.L, Finger.PINKY): (0, 1)}
    assert insights.fingers[0].finger is Finger.RING  # worst first


def test_empty_input():
    assert keystroke_insights([]).is_empty
