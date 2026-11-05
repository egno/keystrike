"""Advice for the next lesson, and the pure rules that keep it safe.

An advisor (hardcoded rules, a small local model, an LLM) is a function
from an `AdvisorContext` to a `LessonAdvice`. The core validates every
advice with `validate_advice` and applies it with `apply_focus_advice` /
`weigh_advice`, whatever the source, so no advisor can delay an unlock,
push weights out of bounds, or name a locked key.

Stdlib only, like the rest of `domain/`."""

from __future__ import annotations

import math
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Final, NamedTuple

from .generator import WordBoost
from .keystroke_insights import KeystrokeInsights
from .models import Bigram, KeyPos, Keystroke, KeyTally, SessionResult

# Change on any change that breaks plugins (see docs/ADVICE-PROTOCOL.md §10).
PLUGIN_API_VERSION: Final = 2

MAX_SUMMARY_CHARS: Final = 200
MAX_PER_KIND: Final = 5
# Evidence floors: a recommendation needs this much to count at all. Weak
# evidence below `FULL_EVIDENCE_EVENTS` scales the effect down.
MIN_EVENTS: Final = 2
MIN_OPPORTUNITIES: Final = 10
FULL_EVIDENCE_EVENTS: Final = 5
# Sampling factors at full effective strength. Deliberately mild: the
# confidence engine stays in charge of what unlocks.
EMPHASIS_RANGE: Final = 0.5  # factor 1.0 .. 1.5
EASE_RANGE: Final = 0.3  # factor 1.0 .. 0.7
EASE_MIN_CONFIDENCE: Final = 1.0
# Lesson words reserved for a contrast drill, at most this share of the lesson.
MAX_RESERVED_SHARE: Final = 0.2
# Shrinks the error rate of rarely typed keys toward zero, so one miss in
# two attempts does not outrank a key that fails every fifth press.
ERROR_RATE_PRIOR: Final = 3

# A CONTRAST needs more: this many events, seen in this many sessions.
CONTRAST_MIN_EVENTS: Final = 3
CONTRAST_MIN_EVENT_SESSIONS: Final = 2
# A recommendation needs this many events to lead the summary.
HEADLINE_MIN_EVENTS: Final = 3

NOT_ENOUGH_DATA: Final = "Not enough data yet — keep practicing."
ON_TRACK: Final = "On track — nothing needs extra practice."

# Recency: session `i` (0 = the newest) weighs `decay ** i`. The advisor reads
# the weighted numbers to rank and to set strength; the raw counts stay the
# evidence. 1.0 means every session in the window weighs the same.
DEFAULT_RECENCY_DECAY: Final = 0.85


@dataclass(frozen=True, slots=True)
class CourseState:
    """Where the learner is in the course, from the latest session."""

    unlocked: tuple[int, ...]  # learning order; last = newest key
    target_cpm: int
    confidence: Mapping[int, float]

    @property
    def newest(self) -> int | None:
        return self.unlocked[-1] if self.unlocked else None

    @property
    def goal_ms(self) -> float:
        """The speed goal as milliseconds per key (0 when there is no goal)."""
        return 60_000.0 / self.target_cpm if self.target_cpm > 0 else 0.0


def session_weights(count: int, decay: float) -> tuple[float, ...]:
    """The weight of each of `count` sessions, newest first."""
    return tuple(decay**i for i in range(count))


@dataclass(frozen=True, slots=True)
class KeyTiming:
    """How fast one key was typed, from the raw keystroke streams of the
    window. Only *eligible* intervals count (see `domain/timing.py`): correct
    first attempts, not a rollover (under 30 ms), not the first press after an
    error, not the first press of a session, and not after a space (a space
    absorbs the pause for planning the next word, so the next key looks fast).

    All counts are exact. `recent_median_ms` is the median with older sessions
    weighing less; classify speed on it, and use the exact counts as evidence."""

    presses: int  # eligible intervals
    over_goal: int  # intervals above the goal
    tail: int  # intervals above 2 x the goal
    median_ms: float  # exact median over the window
    recent_median_ms: float  # weighted median: recent sessions weigh more
    sessions: int  # sessions that contribute


class RecentTally(NamedTuple):
    """A key's tally with older sessions weighted down (floats)."""

    samples: float
    time_ns: float
    errors: float
    attempts: float

    @property
    def mean_ms(self) -> float:
        return self.time_ns / self.samples / 1e6 if self.samples else 0.0

    @property
    def error_rate(self) -> float:
        return self.errors / self.attempts if self.attempts else 0.0


Tally = KeyTally | RecentTally


@dataclass(frozen=True, slots=True)
class AdviceDigest:
    """Per-key and per-pair tallies merged across the window, limited to
    the unlocked keys. Built once by the core so advisors do not repeat it.

    `keys` and `pairs` are exact counts: use them as evidence. `recent` is
    the same per-key tally with older sessions weighted down: use it to rank
    and to decide how strong a recommendation is."""

    keys: Mapping[int, KeyTally] = field(default_factory=dict[int, KeyTally])
    pairs: Mapping[Bigram, KeyTally] = field(default_factory=dict[Bigram, KeyTally])
    recent: Mapping[int, RecentTally] = field(default_factory=dict[int, RecentTally])
    # Timing of each unlocked letter key from the raw streams; empty without streams.
    timing: Mapping[int, KeyTiming] = field(default_factory=dict[int, KeyTiming])
    # The space press, reported on its own (lessons cannot target it).
    space: KeyTiming | None = None

    @property
    def is_empty(self) -> bool:
        return not self.keys


@dataclass(frozen=True, slots=True)
class Coverage:
    """How many sessions each part of the context covers. Raw streams only
    exist for recent sessions, so they often cover fewer than the tallies."""

    digest_sessions: int = 0  # sessions behind the key and pair tallies
    stream_sessions: int = 0  # sessions behind the keystrokes and insights


@dataclass(frozen=True, slots=True)
class AdvisorContext:
    """Everything an advisor may read. Built by the core; read-only."""

    layout: str
    sessions: tuple[SessionResult, ...]  # newest first, confidence window
    course: CourseState
    digest: AdviceDigest
    insights: KeystrokeInsights  # mistypes, errors per finger (per position)
    # session id -> raw stream; empty unless the advisor needs keystrokes
    keystrokes: Mapping[str, Sequence[Keystroke]] = field(
        default_factory=dict[str, Sequence[Keystroke]]
    )
    layout_keys: Mapping[int, KeyPos] = field(default_factory=dict[int, KeyPos])
    coverage: Coverage = Coverage()
    # Weight of each session in `sessions` (newest first); see `session_weights`.
    session_weights: tuple[float, ...] = ()


class Reason(StrEnum):
    ACCURACY = "accuracy"  # errors on the key
    SPEED = "speed"  # correct, but slower than the target
    CONFUSION = "confusion"  # another key was typed instead
    MASTERED = "mastered"  # fast and accurate


class Kind(StrEnum):
    FOCUS = "focus"  # keys = (key,)
    FOCUS_PAIR = "focus_pair"  # keys = (previous, next)
    EMPHASIZE = "emphasize"  # keys = (key,): practice it more
    EASE = "ease"  # keys = (key,): practice it less (reason MASTERED)
    CONTRAST = "contrast"  # keys = (target, typed)


@dataclass(frozen=True, slots=True)
class Evidence:
    """What supports a recommendation, counted over the whole recommendation.
    An error is counted once per position, not once per wrong keystroke."""

    events: int  # errors, slow presses, mistypes; for MASTERED: correct presses
    opportunities: int  # presses that could have shown it
    sessions: int = 0  # sessions the numbers cover
    # Sessions the events come from (None = unknown). A CONTRAST needs several.
    event_sessions: int | None = None


NO_EVIDENCE: Final = Evidence(0, 0)


@dataclass(frozen=True, slots=True)
class Recommendation:
    kind: Kind
    keys: tuple[int, ...]
    reason: Reason
    strength: float = 0.5  # 0..1, the advisor's priority
    evidence: Evidence = NO_EVIDENCE
    # Effective strength: `strength` scaled by the evidence. Set by
    # `validate_advice`; the core effects read only this.
    applied: float = 0.0


@dataclass(frozen=True, slots=True)
class LessonAdvice:
    """What an advisor returns. Codepoints only.

    `error` is non-empty when the advice could not be produced (advisor
    raised, provider down); there are then no recommendations."""

    source: str = ""  # advisor name; set by the runner
    summary: str = ""
    recommendations: tuple[Recommendation, ...] = ()
    created_at: float = 0.0  # unix epoch; set by the runner; 0 = unknown
    error: str = ""

    @property
    def failed(self) -> bool:
        return bool(self.error)

    @property
    def actionable(self) -> bool:
        """True when the advice can change a lesson (a summary alone cannot)."""
        return bool(self.recommendations)

    def of_kind(self, *kinds: Kind) -> tuple[Recommendation, ...]:
        return tuple(r for r in self.recommendations if r.kind in kinds)


EMPTY_ADVICE: Final = LessonAdvice()

Advisor = Callable[[AdvisorContext], Awaitable[LessonAdvice]]
"""An advisor is a function. A stateless advisor (rules) is a plain
`async def`; an advisor with state (an LLM client, a loaded model) is a
closure or a callable object. No base class."""


@dataclass(frozen=True, slots=True)
class AdvisorCapabilities:
    needs_keystrokes: bool = False  # core keeps raw keystrokes only if True
    sends_data_off_device: bool = False  # core asks for explicit opt-in if True


@dataclass(frozen=True, slots=True)
class SettingField:
    """One config value an advisor needs. The core draws the form from
    these, so plugins never import Textual."""

    name: str
    label: str
    default: str = ""
    choices: tuple[str, ...] = ()  # non-empty: a select instead of a text input
    env_hint: str = ""  # e.g. "KEYSTRIKE_AI_API_KEY"; shown, never stored


@dataclass(frozen=True, slots=True)
class AdvisorSpec:
    """How to create an advisor. Kept apart from the advisor itself:
    creation (config parsing, client set-up) is not use."""

    name: str  # "rules", "llm", "ml"; also the HUD tag
    label: str  # Settings screen
    capabilities: AdvisorCapabilities
    settings: tuple[SettingField, ...]
    create: Callable[[Mapping[str, str]], Advisor]
    """Parse and validate the advisor's own config section. Raise
    `ValueError` on bad config; the core shows the message."""


@dataclass(frozen=True, slots=True)
class AdvisorConfig:
    """`advisors.toml`: the active advisor, the off-device confirmations,
    and one plain `str -> str` section per advisor."""

    active: str = ""
    confirmed_off_device: tuple[str, ...] = ()
    sections: Mapping[str, Mapping[str, str]] = field(default_factory=dict[str, Mapping[str, str]])
    # How much an older session weighs less: session i weighs decay ** i.
    recency_decay: float = DEFAULT_RECENCY_DECAY

    def section(self, name: str) -> Mapping[str, str]:
        return self.sections.get(name, {})


async def null_advisor(_ctx: AdvisorContext) -> LessonAdvice:
    return EMPTY_ADVICE


NULL_ADVISOR_NAME: Final = "off"
NULL_ADVISOR_SPEC: Final = AdvisorSpec(
    name=NULL_ADVISOR_NAME,
    label="Off",
    capabilities=AdvisorCapabilities(),
    settings=(),
    create=lambda _cfg: null_advisor,
)


# --- helpers shared by advisors (re-exported by `keystrike.plugin_api`) -----


def error_rate_ranked[T: (KeyTally, RecentTally)](
    tallies: Mapping[int, T],
) -> list[tuple[int, T]]:
    """Keys worst first: shrunk error rate, then mean time per key. A rarely
    typed key with one miss does not outrank a key that fails often. Pass
    `digest.recent` to rank with recent sessions weighing more."""

    def order(item: tuple[int, T]) -> tuple[float, float, int]:
        _, t = item
        mean = t.time_ns / t.samples if t.samples else 0.0
        return (-shrunk_error_rate(t), -mean, item[0])

    return sorted(tallies.items(), key=order)


def shrunk_error_rate(t: Tally) -> float:
    return t.errors / (t.attempts + ERROR_RATE_PRIOR)


def format_char(cp: int) -> str:
    """The character if printable, else its U+ code."""
    ch = chr(cp)
    return ch if ch.isprintable() and not ch.isspace() else f"U+{cp:04X}"


def neighbors(layout_keys: Mapping[int, KeyPos], key: int) -> tuple[int, ...]:
    """Keys on the same hand within one row and one column of `key`."""
    pos = layout_keys.get(key)
    if pos is None:
        return ()
    return tuple(
        sorted(
            cp
            for cp, other in layout_keys.items()
            if cp != key
            and not other.shifted
            and other.hand == pos.hand
            and abs(other.row - pos.row) <= 1
            and abs(other.col - pos.col) <= 1
        )
    )


# --- keeping advice safe -----------------------------------------------------

_ONE_KEY_KINDS: Final = (Kind.FOCUS, Kind.EMPHASIZE, Kind.EASE)
_BUDGET_KINDS: Final = (Kind.EMPHASIZE, Kind.EASE)


def _keys_ok(rec: Recommendation, course: CourseState) -> bool:
    """True when the recommendation's keys are allowed. Nothing is trimmed:
    a wrong arity or one bad key drops the whole recommendation."""
    allowed = frozenset(course.unlocked)
    if not all(k in allowed for k in rec.keys):
        return False
    if rec.kind in _ONE_KEY_KINDS:
        if len(rec.keys) != 1:
            return False
        key = rec.keys[0]
        return rec.kind is not Kind.EASE or (
            key != course.newest and course.confidence.get(key, 0.0) >= EASE_MIN_CONFIDENCE
        )
    return len(rec.keys) == 2 and rec.keys[0] != rec.keys[1]  # noqa: PLR2004


def effective_strength(rec: Recommendation) -> float | None:
    """The effective strength, or None when the evidence is below the floor."""
    ev = rec.evidence
    if ev.opportunities < MIN_OPPORTUNITIES:
        return None
    if rec.kind is Kind.EASE:
        if rec.reason is not Reason.MASTERED:
            return None
    elif ev.events < MIN_EVENTS:
        return None
    if rec.kind is Kind.CONTRAST and (
        ev.events < CONTRAST_MIN_EVENTS or (ev.event_sessions or 0) < CONTRAST_MIN_EVENT_SESSIONS
    ):
        return None
    strength = min(1.0, max(0.0, rec.strength))
    return strength * min(1.0, ev.events / FULL_EVIDENCE_EVENTS)


def _budget(recs: list[Recommendation], limit: int) -> list[Recommendation]:
    """`recs` are one-key recommendations of one kind, strongest first. Keep
    the strongest per key, then the `limit` strongest. Whole recommendations
    are dropped; keys are never trimmed."""
    seen: set[int] = set()
    out: list[Recommendation] = []
    for rec in recs:
        if rec.keys[0] not in seen:
            seen.add(rec.keys[0])
            out.append(rec)
    return out[:limit]


def _headline(rec: Recommendation) -> str:
    keys = [format_char(k) for k in rec.keys]
    ev = rec.evidence
    match rec.kind, rec.reason:
        case Kind.CONTRAST, _:
            target, typed = keys
            return (
                f"You typed {typed} instead of {target} {ev.events} times in "
                f"{ev.opportunities} presses — practice {target} and {typed}."
            )
        case Kind.FOCUS, _:
            return (
                f"{keys[0]} needs the most work: {ev.events} errors in {ev.opportunities} presses."
            )
        case Kind.FOCUS_PAIR, _:
            return (
                f"{keys[0]}{keys[1]} needs the most work: "
                f"{ev.events} errors in {ev.opportunities} presses."
            )
        case Kind.EMPHASIZE, Reason.SPEED:
            return f"{keys[0]} is slower than your goal — it gets extra practice."
        case _:
            return f"{keys[0]} has more errors than the others — it gets extra practice."


def render_summary(advice: LessonAdvice) -> str:
    """The summary for validated advice. It names the strongest non-EASE
    recommendation with at least `HEADLINE_MIN_EVENTS` events. When every
    recommendation is EASE (or there are none), it is `ON_TRACK`. Otherwise
    (only weak evidence) it is empty."""
    leads = [
        r
        for r in advice.recommendations
        if r.kind is not Kind.EASE and r.evidence.events >= HEADLINE_MIN_EVENTS
    ]
    if leads:
        return _headline(max(leads, key=lambda r: r.applied))
    if all(r.kind is Kind.EASE for r in advice.recommendations):
        return ON_TRACK
    return ""


def validate_advice(advice: LessonAdvice, course: CourseState) -> LessonAdvice:
    """Make advice safe. A failed advice is returned without recommendations.

    1. Drop what is not allowed: a locked key, the wrong arity (FOCUS,
       EMPHASIZE and EASE take one key; FOCUS_PAIR and CONTRAST two different
       keys), the newest key or an unmastered key in EASE, EASE without
       reason MASTERED. A recommendation is dropped whole, never trimmed.
    2. Drop what has too little evidence (`MIN_EVENTS`, `MIN_OPPORTUNITIES`;
       a CONTRAST needs `CONTRAST_MIN_EVENTS` in `CONTRAST_MIN_EVENT_SESSIONS`)
       or no strength.
    3. Set `applied`: `strength` scaled by `min(1, events / FULL_EVIDENCE_EVENTS)`.
    4. Budget: per kind, the strongest EMPHASIZE per key, then at most
       `ceil(unlocked / 3)` of them; the same for EASE.
    5. At most 5 recommendations per kind; summary at most 200 characters.
       When the advisor wrote no summary, `render_summary` writes it."""
    if advice.failed:
        return LessonAdvice(source=advice.source, created_at=advice.created_at, error=advice.error)
    checked: list[Recommendation] = []
    for rec in advice.recommendations:
        applied = effective_strength(rec)
        if not _keys_ok(rec, course) or applied is None or applied <= 0.0:
            continue  # not allowed, too little evidence, or no strength: no effect
        checked.append(replace(rec, applied=applied))
    limit = math.ceil(len(course.unlocked) / 3)
    kept: list[Recommendation] = []
    for kind in Kind:
        group = sorted((r for r in checked if r.kind is kind), key=lambda r: -r.applied)
        if kind in _BUDGET_KINDS:
            group = _budget(group, limit)
        kept.extend(group[:MAX_PER_KIND])
    validated = replace(advice, recommendations=tuple(kept))
    summary = advice.summary.strip() or render_summary(validated)
    return replace(validated, summary=summary[:MAX_SUMMARY_CHARS])


@dataclass(frozen=True, slots=True)
class FocusChoices:
    """What advice may pick as focus at the engine's current stage."""

    keys: frozenset[int] = frozenset()
    pairs: frozenset[Bigram] | None = frozenset()  # None = any pair of `keys`

    def allows_pair(self, pair: Bigram) -> bool:
        if self.pairs is None:
            return pair.prev_cp in self.keys and pair.next_cp in self.keys
        return pair in self.pairs


NO_CHOICES: Final = FocusChoices()


def apply_focus_advice(
    focus: int,
    bigram: Bigram | None,
    advice: LessonAdvice,
    choices: FocusChoices,
) -> tuple[int, Bigram | None] | None:
    """Tie-breaker: move the focus only inside `choices`, so the next
    unlock is never pushed back. Pairs come before single keys, strongest
    first. Returns the new `(focus, bigram)`, or None when the advice changes
    nothing (not allowed, or the engine already chose it)."""
    picked: tuple[int, Bigram | None] | None = None
    for rec in sorted(advice.of_kind(Kind.FOCUS_PAIR), key=lambda r: -r.applied):
        pair = Bigram(*rec.keys)
        if choices.allows_pair(pair):
            picked = (pair.next_cp, pair)
            break
    if picked is None:
        for rec in sorted(advice.of_kind(Kind.FOCUS), key=lambda r: -r.applied):
            if rec.keys[0] in choices.keys:
                picked = (rec.keys[0], None)
                break
    return None if picked is None or picked == (focus, bigram) else picked


def weigh_advice(
    char_weights: Mapping[str, float],
    advice: LessonAdvice,
    *,
    protected: frozenset[int] = frozenset(),
) -> dict[str, float]:
    """Scale key weights by the recommendations' effective strength:
    EMPHASIZE `1 + 0.5 * applied`, EASE `1 - 0.3 * applied`. A key in several
    recommendations takes the factor farthest from 1.0. `protected` keys (the
    focus and the newest key) are never eased."""
    factors: dict[int, float] = {}
    for rec in advice.of_kind(Kind.EMPHASIZE, Kind.EASE):
        factor = (
            1.0 + EMPHASIS_RANGE * rec.applied
            if rec.kind is Kind.EMPHASIZE
            else 1.0 - EASE_RANGE * rec.applied
        )
        for cp in rec.keys:
            if rec.kind is Kind.EASE and cp in protected:
                continue
            if abs(factor - 1.0) > abs(factors.get(cp, 1.0) - 1.0):
                factors[cp] = factor
    weights = dict(char_weights)
    for cp, factor in factors.items():
        if chr(cp) in weights:
            weights[chr(cp)] *= factor
    return weights


def word_boosts(advice: LessonAdvice, word_count: int) -> tuple[WordBoost, ...]:
    """Word-level boosts: CONTRAST (target, typed) favours words that contain
    both keys and reserves a few lesson words for them."""
    cap = int(word_count * MAX_RESERVED_SHARE)
    return tuple(
        WordBoost(
            needs_all=frozenset(chr(k) for k in rec.keys),
            factor=1.0 + rec.applied,
            min_words=min(round(rec.applied * word_count / 5), cap),
        )
        for rec in advice.of_kind(Kind.CONTRAST)
    )
