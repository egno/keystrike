"""Pure aggregation: turn a session's raw keystrokes into per-key statistics.

Keybr convention: a key's mean_time_ns is the average time from the previous
*correct* keystroke to this one, aggregated per target codepoint. Wrong
keystrokes increment error_count for the codepoint they missed.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

from .confidence import SESSION_RECENCY_DECAY, HasConfidenceFields, is_same_key_transition
from .models import Bigram, KeyStats, Keystroke, LayoutAggregates, SessionResult, TransitionStats


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
            mean_time_ns=(sum(p.time_samples) / len(p.time_samples)) if p.time_samples else 0.0,
            error_count=p.error_count,
            last_seen=session_end_wall,
            attempt_count=p.attempt_count,
        )
        for cp, p in partial.items()
    }


def session_recency_weights(
    session_count: int,
    *,
    decay: float = SESSION_RECENCY_DECAY,
) -> list[float]:
    """Newest session (last in chronological order) gets weight 1.0; each older
    session is multiplied by `decay`."""
    if session_count <= 0:
        return []
    return [decay ** (session_count - 1 - i) for i in range(session_count)]


def _rounded_weighted_count(weighted: float) -> int:
    """Round recency-weighted counts without zeroing fractional evidence."""
    if weighted <= 0:
        return 0
    rounded = round(weighted)
    return max(1, rounded) if rounded == 0 else rounded


@dataclass(frozen=True, slots=True)
class MergedFields:
    """Result of `_weighted_merge_fields`: the shared recency-weighted merge
    math for key stats and transition stats."""

    samples: int
    mean_time_ns: float
    error_count: int
    attempt_count: int
    last_seen: float


def _weighted_merge_fields(
    entries: Sequence[tuple[HasConfidenceFields, float]],
) -> MergedFields:
    weighted_samples = sum(weight * stats.samples for stats, weight in entries)
    weighted_errors = sum(weight * stats.error_count for stats, weight in entries)
    weighted_attempts = sum(weight * stats.attempt_count for stats, weight in entries)
    if weighted_samples > 0:
        mean = (
            sum(stats.mean_time_ns * weight * stats.samples for stats, weight in entries)
            / weighted_samples
        )
    else:
        mean = 0.0
    last_seen = max(stats.last_seen for stats, _ in entries)
    return MergedFields(
        samples=_rounded_weighted_count(weighted_samples),
        mean_time_ns=mean,
        error_count=round(weighted_errors),
        attempt_count=_rounded_weighted_count(weighted_attempts),
        last_seen=last_seen,
    )


def _combine_key_maps_weighted(
    maps: Sequence[dict[int, KeyStats]],
    weights: Sequence[float],
) -> dict[int, KeyStats]:
    """Merge key stats with recency weights on speed, accuracy, and attempts."""
    by_cp: dict[int, list[tuple[KeyStats, float]]] = {}
    for m, weight in zip(maps, weights, strict=True):
        for cp, stats in m.items():
            by_cp.setdefault(cp, []).append((stats, weight))

    out: dict[int, KeyStats] = {}
    for cp, entries in by_cp.items():
        merged = _weighted_merge_fields(entries)
        out[cp] = KeyStats(
            codepoint=cp,
            samples=merged.samples,
            mean_time_ns=merged.mean_time_ns,
            error_count=merged.error_count,
            last_seen=merged.last_seen,
            attempt_count=merged.attempt_count,
        )
    return out


def _combine_transition_maps_weighted(
    maps: Sequence[dict[Bigram, TransitionStats]],
    weights: Sequence[float],
) -> dict[Bigram, TransitionStats]:
    by_key: dict[Bigram, list[tuple[TransitionStats, float]]] = {}
    for m, weight in zip(maps, weights, strict=True):
        for key, stats in m.items():
            by_key.setdefault(key, []).append((stats, weight))

    out: dict[Bigram, TransitionStats] = {}
    for key, entries in by_key.items():
        merged = _weighted_merge_fields(entries)
        out[key] = TransitionStats(
            prev_cp=key.prev_cp,
            next_cp=key.next_cp,
            samples=merged.samples,
            mean_time_ns=merged.mean_time_ns,
            error_count=merged.error_count,
            last_seen=merged.last_seen,
            attempt_count=merged.attempt_count,
        )
    return without_same_key_transitions(out)


def combine_sessions(
    sessions: Sequence[tuple[SessionResult, Iterable[Keystroke]]],
    *,
    recency_decay: float = SESSION_RECENCY_DECAY,
) -> LayoutAggregates:
    """Merge per-session stats into one layout aggregate.

    Sessions must be in chronological order. Recent sessions weigh more on
    mean time, accuracy, and attempt counts so the sample ramp tracks recent
    practice, not stale volume alone.
    """
    if not sessions:
        return LayoutAggregates(keys={}, transitions={})
    materialized = [(header, list(keystrokes)) for header, keystrokes in sessions]
    weights = session_recency_weights(len(materialized), decay=recency_decay)
    key_maps = [aggregate_session(header, keystrokes) for header, keystrokes in materialized]
    transition_maps = [
        aggregate_transitions(header, keystrokes) for header, keystrokes in materialized
    ]
    return LayoutAggregates(
        keys=_combine_key_maps_weighted(key_maps, weights),
        transitions=_combine_transition_maps_weighted(transition_maps, weights),
    )


def infer_key_stat_samples(samples: int, mean_time_ns: float) -> int:
    """Legacy caches recorded `samples=0` alongside a real `mean_time_ns`
    before the schema tracked keystroke counts; treat that as one sample."""
    if samples <= 0 and mean_time_ns > 0:
        return 1
    return samples


def infer_key_stat_attempt_count(samples: int, error_count: int, attempt_count: int) -> int:
    """Legacy caches predate a stored `attempt_count`; treat samples + errors
    as the inferred total whenever the stored value is non-positive."""
    inferred = samples + error_count
    if attempt_count <= 0 and inferred > 0:
        return inferred
    return attempt_count


def merge_key_stats(a: KeyStats, b: KeyStats) -> KeyStats:
    if a.codepoint != b.codepoint:
        raise ValueError(f"codepoint mismatch: {a.codepoint} vs {b.codepoint}")
    total = a.samples + b.samples
    mean = (a.mean_time_ns * a.samples + b.mean_time_ns * b.samples) / total if total > 0 else 0.0
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
    """Display form of a bigram, e.g. `transition_key(ord("a"), ord("b")) ==
    "ab"`. Internal transition dicts are keyed by `Bigram` instances, not this
    string — use this only for display/logging."""
    return Bigram(prev_cp, next_cp).chars()


def without_same_key_transitions(
    transitions: Mapping[Bigram, TransitionStats],
) -> dict[Bigram, TransitionStats]:
    """Drop same-key pairs (aa, ee) from stored transition stats."""
    return {
        key: stats
        for key, stats in transitions.items()
        if not is_same_key_transition(stats.prev_cp, stats.next_cp)
    }


def per_transition_deltas(keystrokes: Iterable[Keystroke]) -> dict[Bigram, list[int]]:
    """Inter-keystroke deltas per prev→next target pair for correct keystrokes."""
    deltas: dict[Bigram, list[int]] = {}
    last_correct_cp: int | None = None
    last_correct_t_ns: int | None = None

    for k in keystrokes:
        if not k.correct:
            continue
        if (
            last_correct_cp is not None
            and last_correct_t_ns is not None
            and not is_same_key_transition(last_correct_cp, k.codepoint)
        ):
            delta = k.t_ns - last_correct_t_ns
            if delta > 0:
                deltas.setdefault(Bigram(last_correct_cp, k.codepoint), []).append(delta)
        last_correct_cp = k.codepoint
        last_correct_t_ns = k.t_ns

    return deltas


def aggregate_transitions(
    result: SessionResult,
    keystrokes: Iterable[Keystroke],
) -> dict[Bigram, TransitionStats]:
    partial: dict[Bigram, _Partial] = {}
    all_keystrokes = list(keystrokes)
    last_correct_cp: int | None = None

    for i, k in enumerate(all_keystrokes):
        if not k.correct:
            if i > 0:
                prev_cp = all_keystrokes[i - 1].codepoint
                if not is_same_key_transition(prev_cp, k.codepoint):
                    key = Bigram(prev_cp, k.codepoint)
                    entry = partial.setdefault(key, _Partial())
                    entry.attempt_count += 1
                    entry.error_count += 1
            continue
        if last_correct_cp is not None and not is_same_key_transition(
            last_correct_cp,
            k.codepoint,
        ):
            key = Bigram(last_correct_cp, k.codepoint)
            partial.setdefault(key, _Partial()).attempt_count += 1
        last_correct_cp = k.codepoint

    for key, samples in per_transition_deltas(all_keystrokes).items():
        partial.setdefault(key, _Partial()).time_samples.extend(samples)

    session_end_wall = result.started_at + result.duration_ns / 1e9

    return without_same_key_transitions(
        {
            key: TransitionStats(
                prev_cp=key.prev_cp,
                next_cp=key.next_cp,
                samples=len(p.time_samples),
                mean_time_ns=(sum(p.time_samples) / len(p.time_samples)) if p.time_samples else 0.0,
                error_count=p.error_count,
                last_seen=session_end_wall,
                attempt_count=p.attempt_count,
            )
            for key, p in partial.items()
        }
    )


def merge_transition_stats(a: TransitionStats, b: TransitionStats) -> TransitionStats:
    if a.prev_cp != b.prev_cp or a.next_cp != b.next_cp:
        raise ValueError(
            f"transition mismatch: {a.prev_cp}→{a.next_cp} vs {b.prev_cp}→{b.next_cp}",
        )
    total = a.samples + b.samples
    mean = (a.mean_time_ns * a.samples + b.mean_time_ns * b.samples) / total if total > 0 else 0.0
    return TransitionStats(
        prev_cp=a.prev_cp,
        next_cp=a.next_cp,
        samples=total,
        mean_time_ns=mean,
        error_count=a.error_count + b.error_count,
        last_seen=max(a.last_seen, b.last_seen),
        attempt_count=a.attempt_count + b.attempt_count,
    )


def combine_transitions(*maps: dict[Bigram, TransitionStats]) -> dict[Bigram, TransitionStats]:
    out: dict[Bigram, TransitionStats] = {}
    for m in maps:
        for key, t in m.items():
            out[key] = merge_transition_stats(out[key], t) if key in out else t
    return without_same_key_transitions(out)
