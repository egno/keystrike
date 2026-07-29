"""Pure aggregation: turn a session's raw keystrokes into per-key statistics.

Keybr convention: a key's mean_time_ns is the average time from the previous
*correct* keystroke to this one, aggregated per target codepoint. Wrong
keystrokes increment error_count for the codepoint they missed.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from .models import KeyStats, Keystroke, LayoutAggregates, SessionResult, TransitionStats


@dataclass(slots=True)
class _Partial:
    time_samples: list[int] = field(default_factory=list[int])
    error_count: int = 0
    attempt_count: int = 0


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
        entry.attempt_count += 1
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
            attempt_count=p.attempt_count,
        )
        for cp, p in partial.items()
    }


def combine_sessions(
    sessions: Sequence[tuple[SessionResult, Iterable[Keystroke]]],
) -> LayoutAggregates:
    """Merge per-session stats into one layout aggregate."""
    if not sessions:
        return LayoutAggregates(keys={}, transitions={})
    key_maps = [aggregate_session(header, keystrokes) for header, keystrokes in sessions]
    transition_maps = [
        aggregate_transitions(header, keystrokes) for header, keystrokes in sessions
    ]
    return LayoutAggregates(
        keys=combine(*key_maps),
        transitions=combine_transitions(*transition_maps),
    )


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
        attempt_count=a.attempt_count + b.attempt_count,
    )


def combine(*maps: dict[int, KeyStats]) -> dict[int, KeyStats]:
    out: dict[int, KeyStats] = {}
    for m in maps:
        for cp, k in m.items():
            out[cp] = merge_key_stats(out[cp], k) if cp in out else k
    return out


def transition_key(prev_cp: int, next_cp: int) -> str:
    return chr(prev_cp) + chr(next_cp)


def per_transition_deltas(keystrokes: Iterable[Keystroke]) -> dict[str, list[int]]:
    """Inter-keystroke deltas per prev→next target pair for correct keystrokes."""
    deltas: dict[str, list[int]] = {}
    last_correct_cp: int | None = None
    last_correct_t_ns: int | None = None

    for k in keystrokes:
        if not k.correct:
            continue
        if last_correct_cp is not None and last_correct_t_ns is not None:
            delta = k.t_ns - last_correct_t_ns
            if delta > 0:
                deltas.setdefault(transition_key(last_correct_cp, k.codepoint), []).append(delta)
        last_correct_cp = k.codepoint
        last_correct_t_ns = k.t_ns

    return deltas


def aggregate_transitions(
    result: SessionResult,
    keystrokes: Iterable[Keystroke],
) -> dict[str, TransitionStats]:
    partial: dict[str, _Partial] = {}
    all_keystrokes = list(keystrokes)
    last_correct_cp: int | None = None

    for i, k in enumerate(all_keystrokes):
        if not k.correct:
            if i > 0:
                key = transition_key(all_keystrokes[i - 1].codepoint, k.codepoint)
                entry = partial.setdefault(key, _Partial())
                entry.attempt_count += 1
                entry.error_count += 1
            continue
        if last_correct_cp is not None:
            key = transition_key(last_correct_cp, k.codepoint)
            partial.setdefault(key, _Partial()).attempt_count += 1
        last_correct_cp = k.codepoint

    for key, samples in per_transition_deltas(all_keystrokes).items():
        partial.setdefault(key, _Partial()).time_samples.extend(samples)

    session_end_wall = result.started_at + result.duration_ns / 1e9

    return {
        key: TransitionStats(
            prev_cp=ord(key[0]),
            next_cp=ord(key[1]),
            samples=len(p.time_samples),
            mean_time_ns=(sum(p.time_samples) / len(p.time_samples))
            if p.time_samples else 0.0,
            error_count=p.error_count,
            last_seen=session_end_wall,
            attempt_count=p.attempt_count,
        )
        for key, p in partial.items()
    }


def merge_transition_stats(a: TransitionStats, b: TransitionStats) -> TransitionStats:
    if a.prev_cp != b.prev_cp or a.next_cp != b.next_cp:
        raise ValueError(
            f"transition mismatch: {a.prev_cp}→{a.next_cp} vs {b.prev_cp}→{b.next_cp}",
        )
    total = a.samples + b.samples
    mean = (
        (a.mean_time_ns * a.samples + b.mean_time_ns * b.samples) / total
        if total > 0 else 0.0
    )
    return TransitionStats(
        prev_cp=a.prev_cp,
        next_cp=a.next_cp,
        samples=total,
        mean_time_ns=mean,
        error_count=a.error_count + b.error_count,
        last_seen=max(a.last_seen, b.last_seen),
        attempt_count=a.attempt_count + b.attempt_count,
    )


def combine_transitions(*maps: dict[str, TransitionStats]) -> dict[str, TransitionStats]:
    out: dict[str, TransitionStats] = {}
    for m in maps:
        for key, t in m.items():
            out[key] = merge_transition_stats(out[key], t) if key in out else t
    return out
