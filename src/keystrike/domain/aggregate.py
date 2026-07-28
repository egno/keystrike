"""Pure aggregation: turn a session's raw keystrokes into per-key statistics.

Keybr convention: a key's mean_time_ns is the average time from the previous
*correct* keystroke to this one, aggregated per target codepoint. Wrong
keystrokes increment error_count for the codepoint they missed.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from .models import KeyStats, Keystroke, SessionResult


@dataclass(slots=True)
class _Partial:
    time_samples: list[int] = field(default_factory=list[int])
    error_count: int = 0


def per_key_deltas(keystrokes: Iterable[Keystroke]) -> dict[int, list[int]]:
    """Chronological inter-keystroke deltas per codepoint: the time from the
    previous *correct* keystroke to this one, for each correct keystroke.

    This is the raw data `aggregate_session` reduces to a mean — also used
    directly by the M4 learning-rate regression, which needs the actual
    per-attempt sequence rather than a summary statistic.
    """
    deltas: dict[int, list[int]] = {}
    last_correct_t_ns: int | None = None

    for k in keystrokes:
        if not k.correct:
            continue
        if last_correct_t_ns is not None:
            delta = k.t_ns - last_correct_t_ns
            if delta > 0:
                deltas.setdefault(k.codepoint, []).append(delta)
        last_correct_t_ns = k.t_ns

    return deltas


def aggregate_session(
    result: SessionResult,
    keystrokes: Iterable[Keystroke],
) -> dict[int, KeyStats]:
    partial: dict[int, _Partial] = {}
    all_keystrokes = list(keystrokes)

    for k in all_keystrokes:
        entry = partial.setdefault(k.codepoint, _Partial())
        if not k.correct:
            entry.error_count += 1

    for cp, deltas in per_key_deltas(all_keystrokes).items():
        partial.setdefault(cp, _Partial()).time_samples.extend(deltas)

    session_end_wall = result.started_at + result.duration_ns / 1e9

    return {
        cp: KeyStats(
            codepoint=cp,
            samples=len(p.time_samples),
            mean_time_ns=(sum(p.time_samples) / len(p.time_samples))
            if p.time_samples else 0.0,
            error_count=p.error_count,
            last_seen=session_end_wall,
        )
        for cp, p in partial.items()
    }


def merge_key_stats(a: KeyStats, b: KeyStats) -> KeyStats:
    if a.codepoint != b.codepoint:
        raise ValueError(f"codepoint mismatch: {a.codepoint} vs {b.codepoint}")
    total = a.samples + b.samples
    mean = (
        (a.mean_time_ns * a.samples + b.mean_time_ns * b.samples) / total
        if total > 0 else 0.0
    )
    return KeyStats(
        codepoint=a.codepoint,
        samples=total,
        mean_time_ns=mean,
        error_count=a.error_count + b.error_count,
        last_seen=max(a.last_seen, b.last_seen),
    )


def combine(*maps: dict[int, KeyStats]) -> dict[int, KeyStats]:
    out: dict[int, KeyStats] = {}
    for m in maps:
        for cp, k in m.items():
            out[cp] = merge_key_stats(out[cp], k) if cp in out else k
    return out
