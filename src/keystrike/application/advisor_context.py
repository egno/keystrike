"""build_advisor_context: the shared feature extraction. The core builds
the digest, course state and keystroke insights once per request so that
no advisor rebuilds them."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace

from keystrike.domain.advice import (
    AdviceDigest,
    AdvisorContext,
    CourseState,
    Coverage,
    KeyTiming,
    RecentTally,
    session_weights,
)
from keystrike.domain.keystroke_insights import KeystrokeInsights, keystroke_insights
from keystrike.domain.models import Bigram, KeyPos, Keystroke, KeyTally, SessionResult
from keystrike.domain.timing import key_timings


def _visible(cp: int) -> bool:
    ch = chr(cp)
    return ch.isprintable() and not ch.isspace()


def _merge(tallies: dict[Bigram | int, KeyTally], key: Bigram | int, tally: KeyTally) -> None:
    old = tallies.get(key)
    if old is None:
        tallies[key] = tally
        return
    tallies[key] = KeyTally(
        samples=old.samples + tally.samples,
        time_ns=old.time_ns + tally.time_ns,
        errors=old.errors + tally.errors,
        attempts=old.attempts + tally.attempts,
    )


def course_state(sessions: Sequence[SessionResult]) -> CourseState:
    """Where the learner is, from the latest session (`sessions[0]`)."""
    if not sessions:
        return CourseState(unlocked=(), target_cpm=0, confidence={})
    latest = sessions[0]
    return CourseState(
        unlocked=tuple(cp for cp in latest.unlocked_keys if _visible(cp)),
        target_cpm=latest.target_speed_cpm,
        confidence=dict(latest.key_confidence),
    )


def advice_digest(
    sessions: Sequence[SessionResult],
    course: CourseState,
    weights: Sequence[float] | None = None,
) -> AdviceDigest:
    """Per-key / per-pair tallies merged across `sessions`, limited to the
    unlocked keys. `weights` (one per session, newest first) also build the
    recency-weighted `recent` tally per key; without them every session weighs 1."""
    allowed = frozenset(course.unlocked)
    weight_list = list(weights) if weights is not None else [1.0] * len(sessions)

    def ok(cp: int) -> bool:
        return cp in allowed and _visible(cp)

    keys: dict[Bigram | int, KeyTally] = {}
    pairs: dict[Bigram | int, KeyTally] = {}
    recent: dict[int, RecentTally] = {}
    for session, weight in zip(sessions, weight_list, strict=True):
        for cp, tally in session.stats.keys.items():
            if ok(cp):
                _merge(keys, cp, tally)
                old = recent.get(cp, RecentTally(0.0, 0.0, 0.0, 0.0))
                recent[cp] = RecentTally(
                    old.samples + weight * tally.samples,
                    old.time_ns + weight * tally.time_ns,
                    old.errors + weight * tally.errors,
                    old.attempts + weight * tally.attempts,
                )
        for pair, tally in session.stats.transitions.items():
            if ok(pair.prev_cp) and ok(pair.next_cp):
                _merge(pairs, pair, tally)
    return AdviceDigest(
        keys={k: v for k, v in keys.items() if isinstance(k, int)},
        pairs={k: v for k, v in pairs.items() if isinstance(k, Bigram)},
        recent=recent,
    )


def build_advisor_context(
    layout: str,
    sessions: Sequence[SessionResult],
    streams: Mapping[str, Sequence[Keystroke]],
    layout_keys: Mapping[int, KeyPos] | None = None,
    recency_decay: float = 1.0,
) -> AdvisorContext:
    """`sessions` newest first, already windowed by the caller. `streams` are
    the raw keystrokes (empty unless the advisor needs them); the insights
    and `digest.timing` / `digest.space` are built only when streams exist.
    `coverage` says how many sessions each part covers: raw streams often
    cover fewer than the tallies.

    `recency_decay` is the weight ratio between a session and the next older
    one (session `i` weighs `decay ** i`). 1.0 weighs all sessions the same."""
    course = course_state(sessions)
    weights = session_weights(len(sessions), recency_decay)
    digest = advice_digest(sessions, course, weights)
    by_session = {s.session_id: w for s, w in zip(sessions, weights, strict=True)}
    stream_weights = [by_session.get(sid, 1.0) for sid in streams]
    insights = KeystrokeInsights()
    if streams:
        insights = keystroke_insights(
            streams.values(), keys=frozenset(digest.keys), weights=stream_weights
        )
        timing, space = key_timings(
            list(streams.values()), stream_weights, course.goal_ms, frozenset(course.unlocked)
        )
        digest = replace(digest, timing=timing, space=space)
    return AdvisorContext(
        layout=layout,
        sessions=tuple(sessions),
        course=course,
        digest=digest,
        insights=insights,
        keystrokes=streams,
        layout_keys=layout_keys or {},
        coverage=Coverage(digest_sessions=len(sessions), stream_sessions=len(streams)),
        session_weights=weights,
    )


def sample_context() -> AdvisorContext:
    """Small synthetic context for `TestAdvisor` (Ctrl+T in Settings)."""
    ms = 1_000_000
    unlocked = tuple(ord(c) for c in "etaoin")
    tallies = {
        ord("e"): KeyTally(samples=40, time_ns=40 * 250 * ms, errors=1, attempts=41),
        ord("t"): KeyTally(samples=30, time_ns=30 * 300 * ms, errors=2, attempts=32),
        ord("a"): KeyTally(samples=25, time_ns=25 * 320 * ms, errors=3, attempts=28),
        ord("o"): KeyTally(samples=20, time_ns=20 * 350 * ms, errors=2, attempts=22),
        ord("i"): KeyTally(samples=12, time_ns=12 * 420 * ms, errors=5, attempts=17),
        ord("n"): KeyTally(samples=8, time_ns=8 * 500 * ms, errors=6, attempts=14),
    }
    course = CourseState(
        unlocked=unlocked,
        target_cpm=175,
        confidence={cp: 0.5 for cp in unlocked},
    )
    # The goal is 343 ms. `n` and `o` are slower than that, the rest are not.
    timing = {
        ord("e"): KeyTiming(40, 8, 1, 240.0, 240.0, 3),
        ord("t"): KeyTiming(30, 9, 1, 300.0, 300.0, 3),
        ord("a"): KeyTiming(25, 10, 2, 330.0, 330.0, 3),
        ord("o"): KeyTiming(20, 14, 3, 390.0, 395.0, 3),
        ord("i"): KeyTiming(12, 6, 1, 330.0, 335.0, 2),
        ord("n"): KeyTiming(24, 20, 5, 480.0, 490.0, 3),
    }
    return AdvisorContext(
        layout="sample",
        sessions=(),
        course=course,
        digest=AdviceDigest(
            keys=tallies,
            pairs={},
            recent={cp: RecentTally(*map(float, t)) for cp, t in tallies.items()},
            timing=timing,
        ),
        insights=KeystrokeInsights(),
        keystrokes={},
        coverage=Coverage(digest_sessions=3, stream_sessions=3),
        session_weights=(1.0, 0.85, 0.7225),
    )
