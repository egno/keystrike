"""Built-in rules advisor: deterministic, no dependencies, fully local.

It registers through the same `register()` path as a plugin.

Every recommendation says why (`reason`) and what supports it (`evidence`).
The core scales the effect by the evidence, so a mistype seen twice gives a
small push and one seen ten times gives a full one. EMPHASIZE and EASE name
one key each. The advisor writes no summary: the core writes it from the
validated recommendations.

**Recency.** The evidence is the exact count over the window. But what to
rank first, and how strong a recommendation is, follow the *recent* numbers:
older sessions weigh less (`digest.recent`, `Confusion.recency`, `recent_*`
on the finger stats). A mistype you stopped making fades; a new one counts
at once.

**Timing.** Speed comes from `digest.timing`: the recency-weighted median of
the eligible intervals of a key, never the mean. A key is slow above 1.05 x
the goal and fast enough to ease at or below 0.95 x the goal. Between the two
lines (the dead band) the key gets no speed advice either way, so advice does
not flip from one session to the next. A key without timing, or a course
without a goal, gets no speed advice."""

from __future__ import annotations

from keystrike.plugin_api import (
    AdvisorCapabilities,
    AdvisorContext,
    AdvisorRegistry,
    AdvisorSpec,
    Evidence,
    Kind,
    LessonAdvice,
    Reason,
    RecentTally,
    Recommendation,
    Tally,
    effective_strength,
    error_rate_ranked,
)

NAME = "rules"
MIN_FOCUS_RATE = 0.08  # shrunk error rate a key needs to become the focus
FOCUS_RATE_FULL = 0.20  # shrunk error rate that gives full strength
MIN_FINGER_ATTEMPTS = 20
FINGER_MARGIN = 1.5  # finger error rate vs the average, to count as "clearly above"
FINGER_RATE_FULL = 0.15
SLOW_MARGIN = 1.05  # recent median vs the goal, to count as slow
FAST_MARGIN = 0.95  # recent median vs the goal, to count as fast enough to ease
SLOW_FULL = 1.5  # recent median vs the goal that gives full strength
MIN_TIMING_PRESSES = 20  # eligible intervals a key needs for speed advice
MIN_TIMING_SESSIONS = 2  # sessions those intervals must come from
CONFUSION_STRENGTH = 0.8
MIN_CONTRAST_EVENTS = 3
MIN_CONTRAST_SESSIONS = 2
MIN_CONTRAST_NEWEST_HALF = 1  # events in the newer half of the streams
REST_MAX_ERROR_RATE = 0.02
REST_STRENGTH = 0.5


def _shrunk(t: Tally) -> float:
    return t.errors / (t.attempts + 3)


def _or(recent: float | None, exact: int) -> float:
    return exact if recent is None else recent


def _recent(ctx: AdvisorContext) -> dict[int, RecentTally]:
    """Per-key tallies with recent sessions weighing more. A context built
    without recency information (a plain digest) weighs every session the same."""
    if ctx.digest.recent:
        return dict(ctx.digest.recent)
    return {cp: RecentTally(*map(float, t)) for cp, t in ctx.digest.keys.items()}


def _speed_ratio(ctx: AdvisorContext, cp: int) -> float | None:
    """Recent median / goal for a key with enough timing, else None."""
    goal = ctx.course.goal_ms
    timing = ctx.digest.timing.get(cp)
    if goal <= 0 or timing is None:
        return None
    if timing.presses < MIN_TIMING_PRESSES or timing.sessions < MIN_TIMING_SESSIONS:
        return None
    return timing.recent_median_ms / goal


def _focus(ctx: AdvisorContext) -> Recommendation | None:
    ranked = error_rate_ranked(_recent(ctx))
    if not ranked:
        return None
    cp, recent = ranked[0]
    rate = _shrunk(recent)
    if rate < MIN_FOCUS_RATE:
        return None
    t = ctx.digest.keys[cp]  # the exact counts are the evidence
    return Recommendation(
        Kind.FOCUS,
        (cp,),
        Reason.ACCURACY,
        strength=min(1.0, rate / FOCUS_RATE_FULL),
        evidence=Evidence(t.errors, t.attempts, ctx.coverage.digest_sessions),
    )


def _contrasts(ctx: AdvisorContext) -> list[Recommendation]:
    """One recommendation per mistype (`typed` instead of `target`) that
    repeats across sessions and still happens in the newer half."""
    recs: list[Recommendation] = []
    for c in ctx.insights.confusions:
        if (
            c.count < MIN_CONTRAST_EVENTS
            or c.sessions < MIN_CONTRAST_SESSIONS
            or c.newest_half < MIN_CONTRAST_NEWEST_HALF
        ):
            continue
        tally = ctx.digest.keys.get(c.target)
        opportunities = tally.attempts if tally is not None else 0
        recs.append(
            Recommendation(
                Kind.CONTRAST,
                (c.target, c.typed),
                Reason.CONFUSION,
                strength=CONFUSION_STRENGTH * c.recency,
                evidence=Evidence(
                    c.count,
                    opportunities,
                    ctx.coverage.stream_sessions,
                    event_sessions=c.sessions,
                ),
            )
        )
    return recs


def _slow_keys(ctx: AdvisorContext) -> list[Recommendation]:
    """Correct but slower than the goal: speed, not accuracy. One key each,
    slowest first."""
    slow: list[tuple[float, Recommendation]] = []
    for cp, timing in ctx.digest.timing.items():
        ratio = _speed_ratio(ctx, cp)
        if ratio is None or ratio <= SLOW_MARGIN:
            continue
        rec = Recommendation(
            Kind.EMPHASIZE,
            (cp,),
            Reason.SPEED,
            strength=min(1.0, (ratio - 1.0) / (SLOW_FULL - 1.0)),
            evidence=Evidence(timing.over_goal, timing.presses, timing.sessions),
        )
        slow.append((ratio, rec))
    return [rec for _, rec in sorted(slow, key=lambda item: (-item[0], item[1].keys))]


def _weak_finger(ctx: AdvisorContext) -> list[Recommendation]:
    """The keys of the finger with the highest recent error rate, if it is
    clearly above average. Each key carries its own exact errors and
    attempts; a key with too little evidence of its own is left out."""
    fingers = [f for f in ctx.insights.fingers if f.attempts >= MIN_FINGER_ATTEMPTS]
    if not fingers:
        return []
    # The average uses the same recent weighting as the worst finger's rate.
    recent_attempts = sum(_or(f.recent_attempts, f.attempts) for f in fingers)
    recent_errors = sum(_or(f.recent_errors, f.errors) for f in fingers)
    average = recent_errors / recent_attempts if recent_attempts else 0.0
    worst = max(fingers, key=lambda f: f.recent_error_rate)
    if worst.errors == 0 or worst.recent_error_rate < average * FINGER_MARGIN:
        return []
    keys = {
        ks.codepoint
        for stream in ctx.keystrokes.values()
        for ks in stream
        if (ks.hand, ks.finger) == (worst.hand, worst.finger) and ks.codepoint in ctx.digest.keys
    }
    recent = _recent(ctx)
    strength = min(1.0, worst.recent_error_rate / FINGER_RATE_FULL)
    recs: list[Recommendation] = []
    for cp, _ in error_rate_ranked({cp: recent[cp] for cp in keys if cp in recent}):
        t = ctx.digest.keys[cp]
        rec = Recommendation(
            Kind.EMPHASIZE,
            (cp,),
            Reason.ACCURACY,
            strength=strength,
            evidence=Evidence(t.errors, t.attempts, ctx.coverage.digest_sessions),
        )
        if _clears_the_bar(rec):
            recs.append(rec)
    return recs


def _is_mastered(ctx: AdvisorContext, cp: int, recent: RecentTally) -> bool:
    ratio = _speed_ratio(ctx, cp)
    return (
        ctx.course.confidence.get(cp, 0.0) >= 1.0
        and recent.attempts > 0
        and recent.errors / recent.attempts < REST_MAX_ERROR_RATE
        and ratio is not None
        and ratio <= FAST_MARGIN
        and cp != ctx.course.newest
    )


def _mastered(ctx: AdvisorContext) -> list[Recommendation]:
    """Keys that are fast and accurate, one each, best first. Never the
    newest key. A key without timing is never eased."""
    recs: list[Recommendation] = []
    for cp, recent in reversed(error_rate_ranked(_recent(ctx))):
        if not _is_mastered(ctx, cp, recent):
            continue
        t = ctx.digest.keys[cp]
        recs.append(
            Recommendation(
                Kind.EASE,
                (cp,),
                Reason.MASTERED,
                strength=REST_STRENGTH,
                evidence=Evidence(t.samples, t.attempts, ctx.coverage.digest_sessions),
            )
        )
    return recs


def _clears_the_bar(rec: Recommendation | None) -> bool:
    """The core would keep it: enough evidence and some strength."""
    return rec is not None and (effective_strength(rec) or 0.0) > 0.0


async def rules_advisor(ctx: AdvisorContext) -> LessonAdvice:
    candidates = [
        _focus(ctx),
        *_contrasts(ctx),
        *_slow_keys(ctx),
        *_weak_finger(ctx),
        *_mastered(ctx),
    ]
    recs = [r for r in candidates if r is not None and _clears_the_bar(r)]
    return LessonAdvice(summary="", recommendations=tuple(recs))


SPEC = AdvisorSpec(
    name=NAME,
    label="Rules (local)",
    # Local only; needs the raw keystrokes for mistypes and per-finger errors.
    capabilities=AdvisorCapabilities(needs_keystrokes=True, sends_data_off_device=False),
    settings=(),
    create=lambda _cfg: rules_advisor,
)


def register(registry: AdvisorRegistry) -> None:
    registry.register(SPEC)
