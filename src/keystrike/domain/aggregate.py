"""Pure aggregation: turn a session's raw keystrokes into per-key statistics.

Keybr convention: a key's mean_time_ns is the average time from the previous
*correct* keystroke to this one, aggregated per target codepoint. Wrong
keystrokes increment error_count for the codepoint they missed.

The reduction happens in two stages. `tally_session` folds the keystroke
stream into exact integer `KeyTally` counters per key and per bigram — that
`SessionStats` is what gets persisted with the session header. `combine_sessions`
then merges the stored tallies of a window of sessions with recency weights.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol

from .confidence import SESSION_RECENCY_DECAY, HasConfidenceFields, is_same_key_transition
from .models import (
    Bigram,
    KeyStats,
    Keystroke,
    KeyTally,
    LayoutAggregates,
    SessionStats,
    TransitionStats,
)


class SessionTiming(Protocol):
    """Structural shape `session_key_stats`/`session_transition_stats`/
    `combine_sessions` need from a session header: only the fields required
    to timestamp aggregated stats, not a full persisted `SessionResult`."""

    @property
    def started_at(self) -> float: ...

    @property
    def duration_ns(self) -> int: ...


@dataclass(slots=True)
class _Partial:
    time_samples: list[int] = field(default_factory=list[int])
    error_count: int = 0
    attempt_count: int = 0

    def tally(self) -> KeyTally:
        return KeyTally(
            samples=len(self.time_samples),
            time_ns=sum(self.time_samples),
            errors=self.error_count,
            attempts=self.attempt_count,
        )


def per_key_deltas(keystrokes: Iterable[Keystroke]) -> dict[int, list[int]]:
    """Chronological inter-keystroke deltas per codepoint: the time from the
    previous *correct* keystroke to this one, for each correct keystroke.

    This is the raw data `tally_session` reduces to a sum — also used
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


def _tally_keys(keystrokes: Sequence[Keystroke]) -> dict[int, KeyTally]:
    partial: dict[int, _Partial] = {}
    for k in keystrokes:
        entry = partial.setdefault(k.codepoint, _Partial())
        entry.attempt_count += 1
        if not k.correct:
            entry.error_count += 1
    for cp, deltas in per_key_deltas(keystrokes).items():
        partial.setdefault(cp, _Partial()).time_samples.extend(deltas)
    return {cp: p.tally() for cp, p in partial.items()}


def _tally_transitions(keystrokes: Sequence[Keystroke]) -> dict[Bigram, KeyTally]:
    partial: dict[Bigram, _Partial] = {}
    last_correct_cp: int | None = None

    for i, k in enumerate(keystrokes):
        if not k.correct:
            if i > 0:
                prev_cp = keystrokes[i - 1].codepoint
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

    for key, samples in per_transition_deltas(keystrokes).items():
        partial.setdefault(key, _Partial()).time_samples.extend(samples)

    # Same-key pairs never enter `partial`: every branch above skips them.
    return {key: p.tally() for key, p in partial.items()}


def tally_session(keystrokes: Iterable[Keystroke]) -> SessionStats:
    """Reduce a session's keystroke stream to its persisted per-key and
    per-bigram tallies. Same-key bigrams (aa, ee) are never tallied."""
    all_keystrokes = list(keystrokes)
    return SessionStats(
        keys=_tally_keys(all_keystrokes),
        transitions=_tally_transitions(all_keystrokes),
    )


def _mean_ns(tally: KeyTally) -> float:
    return tally.time_ns / tally.samples if tally.samples else 0.0


def _session_end_wall(result: SessionTiming) -> float:
    return result.started_at + result.duration_ns / 1e9


def _key_stats_from_tally(codepoint: int, tally: KeyTally, last_seen: float) -> KeyStats:
    return KeyStats(
        codepoint=codepoint,
        samples=tally.samples,
        mean_time_ns=_mean_ns(tally),
        error_count=tally.errors,
        last_seen=last_seen,
        attempt_count=tally.attempts,
    )


def _transition_stats_from_tally(key: Bigram, tally: KeyTally, last_seen: float) -> TransitionStats:
    return TransitionStats(
        prev_cp=key.prev_cp,
        next_cp=key.next_cp,
        samples=tally.samples,
        mean_time_ns=_mean_ns(tally),
        error_count=tally.errors,
        last_seen=last_seen,
        attempt_count=tally.attempts,
    )


def session_key_stats(result: SessionTiming, stats: SessionStats) -> dict[int, KeyStats]:
    """One session's stored key tallies as `KeyStats`, timestamped at session end."""
    end = _session_end_wall(result)
    return {cp: _key_stats_from_tally(cp, t, end) for cp, t in stats.keys.items()}


def session_transition_stats(
    result: SessionTiming, stats: SessionStats
) -> dict[Bigram, TransitionStats]:
    """One session's stored bigram tallies as `TransitionStats`, timestamped at
    session end. Same-key pairs are filtered here, and only here, because the
    tallies may come from stored data rather than from `tally_session`."""
    end = _session_end_wall(result)
    return without_same_key_transitions(
        {key: _transition_stats_from_tally(key, t, end) for key, t in stats.transitions.items()}
    )


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
    sessions: Sequence[tuple[SessionTiming, SessionStats]],
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
    weights = session_recency_weights(len(sessions), decay=recency_decay)
    key_maps = [session_key_stats(header, stats) for header, stats in sessions]
    transition_maps = [session_transition_stats(header, stats) for header, stats in sessions]
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


def without_same_key_transitions(
    transitions: Mapping[Bigram, TransitionStats],
) -> dict[Bigram, TransitionStats]:
    """Drop same-key pairs (aa, ee) from stored transition stats."""
    return {
        key: stats
        for key, stats in transitions.items()
        if not is_same_key_transition(stats.prev_cp, stats.next_cp)
    }
