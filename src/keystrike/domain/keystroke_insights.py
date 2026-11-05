"""What the raw keystroke stream shows that per-key tallies cannot: which
key was typed instead of the target, and which finger makes the errors.

Pure functions over `Keystroke` sequences; used to brief the AI coach."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from .enums import Finger, Hand
from .models import Keystroke


@dataclass(frozen=True, slots=True)
class Confusion:
    target: int
    typed: int
    count: int


@dataclass(frozen=True, slots=True)
class FingerErrors:
    hand: Hand | None
    finger: Finger
    errors: int
    attempts: int

    @property
    def error_rate(self) -> float:
        return self.errors / self.attempts if self.attempts else 0.0


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


def keystroke_insights(
    streams: Iterable[Sequence[Keystroke]],
    *,
    keys: frozenset[int] | None = None,
    max_confusions: int = 5,
    min_confusion_count: int = 2,
) -> KeystrokeInsights:
    """Top mistypes and per-finger error rates across `streams`.

    Only visible target characters count; `keys`, when given, limits the
    result to those targets (for example, the unlocked keys). A mistype must
    repeat at least `min_confusion_count` times to be reported."""
    confusions: Counter[tuple[int, int]] = Counter()
    attempts: Counter[tuple[Hand | None, Finger]] = Counter()
    errors: Counter[tuple[Hand | None, Finger]] = Counter()
    for stream in streams:
        for ks in stream:
            if not _visible(ks.codepoint) or (keys is not None and ks.codepoint not in keys):
                continue
            if not ks.correct and _visible(ks.typed):
                confusions[(ks.codepoint, ks.typed)] += 1
            if ks.finger is not None:
                slot = (ks.hand, ks.finger)
                attempts[slot] += 1
                if not ks.correct:
                    errors[slot] += 1
    top = tuple(
        Confusion(target=t, typed=y, count=n)
        for (t, y), n in sorted(confusions.items(), key=lambda kv: (-kv[1], kv[0]))
        if n >= min_confusion_count
    )[:max_confusions]
    fingers = tuple(
        sorted(
            (
                FingerErrors(hand=hand, finger=finger, errors=errors[(hand, finger)], attempts=n)
                for (hand, finger), n in attempts.items()
            ),
            key=lambda f: (-f.error_rate, -f.attempts),
        )
    )
    return KeystrokeInsights(confusions=top, fingers=fingers)
