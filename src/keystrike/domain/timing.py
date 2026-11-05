"""Per-key timing from the raw keystroke streams.

Only *eligible* intervals count. An interval is the time from the previous
position's first attempt to this position's first attempt. It is eligible
when all of these are true:

- this first attempt is correct;
- it is not the first press of the session;
- the previous position's first attempt was correct (the first press after
  an error is not timed: the retries and the recovery sit in the interval);
- the previous target is not a space (the space absorbs the pause for
  planning the next word, so the next key looks fast);
- the target is not a space (the space is reported on its own);
- the interval is at least `MIN_INTERVAL_MS` (shorter is key rollover).

The space press uses the same rules, except the last two about a space.

Pure functions; stdlib and domain only."""

from __future__ import annotations

import statistics
from collections.abc import Collection, Iterable, Iterator, Sequence
from typing import Final

from .advice import KeyTiming
from .keystroke_insights import first_attempts
from .models import Keystroke

MIN_INTERVAL_MS: Final = 30.0  # shorter intervals are key rollover
TAIL_FACTOR: Final = 2.0  # a tail interval is above TAIL_FACTOR x the goal
SPACE: Final = ord(" ")


def _intervals(stream: Sequence[Keystroke], *, space: bool) -> Iterator[tuple[Keystroke, float]]:
    """Eligible intervals of letters (`space=False`) or of the space press."""
    previous: Keystroke | None = None
    for ks in first_attempts(stream):
        before, previous = previous, ks
        if before is None or not ks.correct or not before.correct:
            continue
        if space:
            if ks.codepoint != SPACE:
                continue
        elif SPACE in (ks.codepoint, before.codepoint):
            continue
        interval = (ks.t_ns - before.t_ns) / 1e6
        if interval >= MIN_INTERVAL_MS:
            yield ks, interval


def eligible_intervals(stream: Sequence[Keystroke]) -> Iterator[tuple[Keystroke, float]]:
    """Each eligible keystroke of one stream with its interval in ms."""
    return _intervals(stream, space=False)


def space_intervals(stream: Sequence[Keystroke]) -> Iterator[tuple[Keystroke, float]]:
    """Each eligible space press of one stream with its interval in ms."""
    return _intervals(stream, space=True)


def weighted_median(values_and_weights: Iterable[tuple[float, float]]) -> float:
    """The value where half of the total weight lies on each side. When the
    cumulative weight hits exactly one half, the result is the mean of the two
    neighbouring values, so equal weights give the usual median. Zero or
    negative weights are ignored; no values give 0.0."""
    pairs = sorted((v, w) for v, w in values_and_weights if w > 0)
    if not pairs:
        return 0.0
    half = sum(w for _, w in pairs) / 2
    cumulative = 0.0
    for i, (value, weight) in enumerate(pairs):
        cumulative += weight
        if abs(cumulative - half) <= 1e-9 * half and i + 1 < len(pairs):
            return (value + pairs[i + 1][0]) / 2
        if cumulative > half:
            return value
    return pairs[-1][0]


def _key_timing(samples: Sequence[tuple[float, float, int]], goal_ms: float) -> KeyTiming:
    """`samples` are (interval, weight, stream index)."""
    values = [v for v, _, _ in samples]
    over = sum(1 for v in values if v > goal_ms) if goal_ms > 0 else 0
    tail = sum(1 for v in values if v > TAIL_FACTOR * goal_ms) if goal_ms > 0 else 0
    return KeyTiming(
        presses=len(values),
        over_goal=over,
        tail=tail,
        median_ms=statistics.median(values),
        recent_median_ms=weighted_median((v, w) for v, w, _ in samples),
        sessions=len({s for _, _, s in samples}),
    )


def key_timings(
    streams: Sequence[Sequence[Keystroke]],
    weights: Sequence[float],
    goal_ms: float,
    keys: Collection[int],
) -> tuple[dict[int, KeyTiming], KeyTiming | None]:
    """Timing of each key in `keys` and of the space press, over `streams`.

    `weights` (one per stream) weigh the recent median only; every count is
    exact. A key without an eligible interval is left out. The space timing
    is None when the space has no eligible interval. With a goal of 0,
    `over_goal` and `tail` are 0."""
    by_key: dict[int, list[tuple[float, float, int]]] = {}
    space: list[tuple[float, float, int]] = []
    for index, (stream, weight) in enumerate(zip(streams, weights, strict=True)):
        for ks, interval in eligible_intervals(stream):
            if ks.codepoint in keys:
                by_key.setdefault(ks.codepoint, []).append((interval, weight, index))
        space.extend((interval, weight, index) for _, interval in space_intervals(stream))
    timings = {cp: _key_timing(samples, goal_ms) for cp, samples in by_key.items()}
    return timings, (_key_timing(space, goal_ms) if space else None)
