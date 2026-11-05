"""What the raw keystroke stream shows that per-key tallies cannot: which
key was typed instead of the target, and which finger makes the errors.

Pure functions over `Keystroke` sequences; used to brief advisors.

The cursor does not advance on an error, so a wrong key is followed by
retries of the same target. All attempts at one position count once: only
the first attempt is an attempt, and only a wrong first attempt is an
error. Without this, one stumble of three wrong keys would count as three
mistypes."""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field

from .enums import Finger, Hand
from .models import Keystroke


@dataclass(frozen=True, slots=True)
class Confusion:
    """`typed` was pressed at a position whose target was `target`. `count`
    is the raw number of times (the evidence). `recent_count` is the same
    count with older sessions weighted down; None = no recency information."""

    target: int
    typed: int
    count: int
    recent_count: float | None = field(default=None, compare=False)
    # How many sessions (streams) the mistype was seen in, and how many of its
    # events fall in the newer half of the streams (streams are newest first).
    sessions: int = field(default=0, compare=False)
    newest_half: int = field(default=0, compare=False)

    @property
    def recency(self) -> float:
        """Share of the events that is recent, 0..1 (1 when unknown)."""
        if self.recent_count is None or self.count <= 0:
            return 1.0
        return min(1.0, self.recent_count / self.count)


@dataclass(frozen=True, slots=True)
class FingerErrors:
    hand: Hand | None
    finger: Finger
    errors: int
    attempts: int
    # The same counts with older sessions weighted down; None = no recency information.
    recent_errors: float | None = field(default=None, compare=False)
    recent_attempts: float | None = field(default=None, compare=False)

    @property
    def error_rate(self) -> float:
        return self.errors / self.attempts if self.attempts else 0.0

    @property
    def recent_error_rate(self) -> float:
        """The error rate with recent sessions weighing more (the plain rate
        when there is no recency information)."""
        if self.recent_errors is None or self.recent_attempts is None:
            return self.error_rate
        return self.recent_errors / self.recent_attempts if self.recent_attempts else 0.0


@dataclass(frozen=True, slots=True)
class KeystrokeInsights:
    confusions: tuple[Confusion, ...] = ()
    fingers: tuple[FingerErrors, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not self.confusions and not self.fingers


def _visible(cp: int) -> bool:
    ch = chr(cp)
    return ch.isprintable() and not ch.isspace()


def first_attempts(stream: Sequence[Keystroke]) -> Iterator[Keystroke]:
    """The first keystroke at each position of one stream. A wrong key is
    followed by retries of the same target; those are skipped. A first attempt
    is correct only when the position was typed right the first time."""
    previous: Keystroke | None = None
    for ks in stream:
        retry = previous is not None and not previous.correct and previous.codepoint == ks.codepoint
        previous = ks
        if not retry:
            yield ks


def keystroke_insights(
    streams: Iterable[Sequence[Keystroke]],
    *,
    keys: frozenset[int] | None = None,
    max_confusions: int = 5,
    min_confusion_count: int = 2,
    weights: Sequence[float] | None = None,
) -> KeystrokeInsights:
    """Top mistypes and per-finger error rates across `streams`.

    Only visible target characters count; `keys`, when given, limits the
    result to those targets (for example, the unlocked keys). A mistype must
    repeat at least `min_confusion_count` times to be reported.

    `streams` are newest first. `Confusion.sessions` counts the streams where
    the mistype occurs, and `Confusion.newest_half` its events in the newer
    half of the streams (the first `ceil(n / 2)` of `n`).

    `weights`, one per stream, say how much each stream weighs (for example,
    less for older sessions). The plain counts stay exact; the weighted
    counts are added next to them as `recent_*` and never replace them."""
    confusions: Counter[tuple[int, int]] = Counter()
    attempts: Counter[tuple[Hand | None, Finger]] = Counter()
    errors: Counter[tuple[Hand | None, Finger]] = Counter()
    recent_confusions: defaultdict[tuple[int, int], float] = defaultdict(float)
    recent_attempts: defaultdict[tuple[Hand | None, Finger], float] = defaultdict(float)
    recent_errors: defaultdict[tuple[Hand | None, Finger], float] = defaultdict(float)
    confusion_streams: defaultdict[tuple[int, int], set[int]] = defaultdict(set)
    newest_half: Counter[tuple[int, int]] = Counter()
    stream_list = list(streams)
    weight_list = list(weights) if weights is not None else [1.0] * len(stream_list)
    # Streams are newest first: the newer half is the first ceil(n / 2).
    newer = math.ceil(len(stream_list) / 2)
    for index, (stream, weight) in enumerate(zip(stream_list, weight_list, strict=True)):
        for ks in first_attempts(stream):
            if not _visible(ks.codepoint) or (keys is not None and ks.codepoint not in keys):
                continue
            if not ks.correct and _visible(ks.typed):
                pair = (ks.codepoint, ks.typed)
                confusions[pair] += 1
                recent_confusions[pair] += weight
                confusion_streams[pair].add(index)
                if index < newer:
                    newest_half[pair] += 1
            if ks.finger is not None:
                slot = (ks.hand, ks.finger)
                attempts[slot] += 1
                recent_attempts[slot] += weight
                if not ks.correct:
                    errors[slot] += 1
                    recent_errors[slot] += weight
    top = tuple(
        Confusion(
            target=t,
            typed=y,
            count=n,
            recent_count=recent_confusions[(t, y)],
            sessions=len(confusion_streams[(t, y)]),
            newest_half=newest_half[(t, y)],
        )
        for (t, y), n in sorted(confusions.items(), key=lambda kv: (-kv[1], kv[0]))
        if n >= min_confusion_count
    )[:max_confusions]
    fingers = tuple(
        sorted(
            (
                FingerErrors(
                    hand=hand,
                    finger=finger,
                    errors=errors[(hand, finger)],
                    attempts=n,
                    recent_errors=recent_errors[(hand, finger)],
                    recent_attempts=recent_attempts[(hand, finger)],
                )
                for (hand, finger), n in attempts.items()
            ),
            key=lambda f: (-f.error_rate, -f.attempts),
        )
    )
    return KeystrokeInsights(confusions=top, fingers=fingers)
