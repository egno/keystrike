"""AiAnalyzer: ask an LLM coach for suggestions based on recent sessions.

Opt-in (`AiSettings.provider`); nothing leaves the machine unless a provider
is configured. The model answers with plain characters; this module maps them
onto codepoints and drops anything that is not an unlocked key it was shown,
so a hallucinated reply can never steer a lesson at an unknown key.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from typing import Any, Final, cast

from keystrike.domain.ai_models import AiAnalysis, AiSettings
from keystrike.domain.confidence import target_ms_per_char
from keystrike.domain.enums import Finger, Hand
from keystrike.domain.keystroke_insights import KeystrokeInsights, keystroke_insights
from keystrike.domain.models import Bigram, KeyTally, SessionResult
from keystrike.domain.protocols import (
    AiAnalysisStore,
    AiSettingsRepository,
    ChatClient,
    KeystrokeArchive,
    SettingsRepository,
)

logger = logging.getLogger(__name__)

ClientFactory = Callable[[AiSettings], ChatClient]

_MAX_SUMMARY_CHARS = 200
_MAX_KEY_LIST = 5
_PROMPT_TOP_KEYS = 8
_PROMPT_TOP_PAIRS = 5
_PAIR_LEN = 2
# Shrinks the error rate of rarely typed keys toward zero, so one miss in
# two attempts does not outrank a key that fails every fifth press.
_ERROR_RATE_PRIOR = 3

_SYSTEM_PROMPT: Final = (
    "You are a typing coach analyzing recent practice sessions of an adaptive "
    "typing tutor. The tutor unlocks new keys by itself once the current keys "
    "are fast and accurate; you only tune what the next lesson emphasizes.\n"
    "Respond with ONLY a JSON object, no markdown and no extra text:\n"
    "{\n"
    '  "summary": "one or two short sentences of actionable feedback",\n'
    '  "focus_key": "single character, or null",\n'
    '  "focus_pair": "two characters, e.g. \\"th\\", or null",\n'
    '  "rest_keys": ["strong characters to practice a bit less"],\n'
    '  "emphasis_keys": ["characters to practice more next session"]\n'
    "}\n"
    "Rules:\n"
    "- Use only characters from the unlocked keys, never numeric codes.\n"
    "- focus_key: the single key that needs the most work.\n"
    "- focus_pair: a key pair from the data with many errors, or null.\n"
    "- rest_keys: keys that are already fast and accurate. Never the newest key.\n"
    "- rest_keys and emphasis_keys: at most 5 characters each, no overlap.\n"
    "- Use the mistype and finger data to explain the cause in the summary "
    "(for example, which key the user hits instead).\n"
)

_NULLABLE_STRING: Final = {"type": ["string", "null"]}
_KEY_LIST: Final = {"type": "array", "items": {"type": "string"}, "maxItems": _MAX_KEY_LIST}
RESPONSE_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "focus_key": _NULLABLE_STRING,
        "focus_pair": _NULLABLE_STRING,
        "rest_keys": _KEY_LIST,
        "emphasis_keys": _KEY_LIST,
    },
    "required": ["summary", "focus_key", "focus_pair", "rest_keys", "emphasis_keys"],
    "additionalProperties": False,
}


def _show(cp: int) -> str:
    return chr(cp)


def _visible(cp: int) -> bool:
    ch = chr(cp)
    return ch.isprintable() and not ch.isspace()


def _merge(tallies: dict[Any, KeyTally], key: Any, tally: KeyTally) -> None:
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


def _mean_ms(t: KeyTally) -> float:
    return t.time_ns / t.samples / 1e6 if t.samples else 0.0


def _rank_error_rate(t: KeyTally) -> float:
    return t.errors / (t.attempts + _ERROR_RATE_PRIOR)


@dataclass(frozen=True, slots=True)
class _CourseState:
    """Where the learner is in the course, from the latest session."""

    unlocked: tuple[int, ...]
    target_cpm: int
    confidence: dict[int, float]

    @property
    def newest(self) -> int | None:
        return self.unlocked[-1] if self.unlocked else None


def _course_state(sessions: Sequence[SessionResult]) -> _CourseState:
    if not sessions:
        return _CourseState(unlocked=(), target_cpm=0, confidence={})
    latest = sessions[0]
    return _CourseState(
        unlocked=tuple(cp for cp in latest.unlocked_keys if _visible(cp)),
        target_cpm=latest.target_speed_cpm,
        confidence=dict(latest.key_confidence),
    )


class _Digest:
    """Per-key / per-pair tallies merged across the sessions shown to the
    model, limited to the unlocked keys when the sessions record them."""

    def __init__(self, sessions: Sequence[SessionResult], course: _CourseState) -> None:
        allowed = frozenset(course.unlocked) if course.unlocked else None

        def ok(cp: int) -> bool:
            return _visible(cp) and (allowed is None or cp in allowed)

        self.keys: dict[int, KeyTally] = {}
        self.pairs: dict[Bigram, KeyTally] = {}
        for session in sessions:
            for cp, tally in session.stats.keys.items():
                if ok(cp):
                    _merge(self.keys, cp, tally)
            for pair, tally in session.stats.transitions.items():
                if ok(pair.prev_cp) and ok(pair.next_cp):
                    _merge(self.pairs, pair, tally)

    @property
    def known(self) -> frozenset[int]:
        return frozenset(self.keys)

    def is_empty(self) -> bool:
        return not self.keys


_FINGER_NAMES: Final = {
    Finger.PINKY: "pinky",
    Finger.RING: "ring finger",
    Finger.MIDDLE: "middle finger",
    Finger.INDEX: "index finger",
    Finger.THUMB: "thumb",
}
_HAND_NAMES: Final = {Hand.L: "left", Hand.R: "right"}


def _course_lines(course: _CourseState) -> list[str]:
    lines: list[str] = []
    if course.target_cpm > 0:
        target_ms = target_ms_per_char(course.target_cpm)
        lines.append(f"Goal: {course.target_cpm} CPM ({target_ms:.0f} ms per key).")
    if course.unlocked:
        lines.append(
            "Unlocked keys, in learning order: " + " ".join(_show(cp) for cp in course.unlocked)
        )
    if course.newest is not None:
        lines.append(f"Newest key (being learned now): {_show(course.newest)}")
    return lines


def _key_lines(digest: _Digest, course: _CourseState) -> list[str]:
    def order(item: tuple[int, KeyTally]) -> tuple[float, float]:
        _, t = item
        return (-_rank_error_rate(t), -_mean_ms(t))

    lines = ["Keys, worst first (error rate, mean time per key, confidence 0-1, 1 = mastered):"]
    for cp, t in sorted(digest.keys.items(), key=order)[:_PROMPT_TOP_KEYS]:
        rate = t.errors / t.attempts if t.attempts else 0.0
        line = f"- '{_show(cp)}': {rate:.0%} errors ({t.errors}/{t.attempts}), {_mean_ms(t):.0f} ms"
        if cp in course.confidence:
            line += f", confidence {course.confidence[cp]:.2f}"
        lines.append(line)
    return lines


def _pair_lines(digest: _Digest) -> list[str]:
    worst = sorted(digest.pairs.items(), key=lambda kv: -_rank_error_rate(kv[1]))
    worst = [(p, t) for p, t in worst if t.errors > 0][:_PROMPT_TOP_PAIRS]
    if not worst:
        return []
    return ["Key pairs with errors:"] + [
        f"- '{_show(p.prev_cp)}{_show(p.next_cp)}': {t.errors} errors / {t.attempts} attempts"
        for p, t in worst
    ]


def _insight_lines(insights: KeystrokeInsights) -> list[str]:
    lines: list[str] = []
    if insights.confusions:
        lines.append("Common mistypes (target typed as):")
        lines.extend(
            f"- '{_show(c.target)}' typed as '{_show(c.typed)}': {c.count} times"
            for c in insights.confusions
        )
    fingers = [f for f in insights.fingers if f.errors > 0]
    if fingers:
        lines.append("Errors by finger:")
        for f in fingers:
            hand = f"{_HAND_NAMES[f.hand]} " if f.hand is not None else ""
            lines.append(
                f"- {hand}{_FINGER_NAMES[f.finger]}: {f.error_rate:.0%} ({f.errors}/{f.attempts})"
            )
    return lines


def _build_user_prompt(
    sessions: Sequence[SessionResult],
    digest: _Digest,
    course: _CourseState,
    insights: KeystrokeInsights,
) -> str:
    lines = _course_lines(course)
    lines.append(f"Last {len(sessions)} session(s), latest first:")
    for i, s in enumerate(sessions, 1):
        accuracy = s.correct_keystrokes / s.total_keystrokes if s.total_keystrokes else 0.0
        lines.append(f"- session {i}: {s.cpm:.0f} CPM, {accuracy:.0%} accuracy")
    lines.extend(_key_lines(digest, course))
    lines.extend(_pair_lines(digest))
    lines.extend(_insight_lines(insights))
    return "\n".join(lines)


def _as_cp(value: Any, known: frozenset[int]) -> int | None:
    if isinstance(value, str) and len(value) == 1 and ord(value) in known:
        return ord(value)
    return None


def _as_cp_list(value: Any, known: frozenset[int]) -> tuple[int, ...]:
    if not isinstance(value, list):
        return ()
    out: list[int] = []
    for item in cast("list[Any]", value):
        cp = _as_cp(item, known)
        if cp is not None and cp not in out:
            out.append(cp)
    return tuple(out[:_MAX_KEY_LIST])


def _as_pair(value: Any, known: frozenset[int]) -> Bigram | None:
    chars: list[Any]
    if isinstance(value, str) and len(value) == _PAIR_LEN:
        chars = list(value)
    elif isinstance(value, list) and len(cast("list[Any]", value)) == _PAIR_LEN:
        chars = list(cast("list[Any]", value))
    else:
        return None
    first, second = _as_cp(chars[0], known), _as_cp(chars[1], known)
    if first is None or second is None or first == second:
        return None
    return Bigram(first, second)


def _extract_json_object(text: str) -> Any:
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object in reply")
    return json.loads(text[start : end + 1])


def parse_response(
    text: str,
    known: frozenset[int],
    *,
    protected: frozenset[int] = frozenset(),
) -> AiAnalysis:
    """Parse a model reply. Invalid individual fields are dropped; a reply that
    is not a JSON object raises `ValueError`. Keys in `protected` (the newest
    key) are never put on the rest list, and a key the model lists both ways
    stays on the emphasis list only."""
    parsed = _extract_json_object(text)
    if not isinstance(parsed, dict):
        raise ValueError("reply is not a JSON object")
    data = cast("dict[str, Any]", parsed)
    summary: Any = data.get("summary")
    emphasis = _as_cp_list(data.get("emphasis_keys"), known)
    rest = tuple(
        cp
        for cp in _as_cp_list(data.get("rest_keys"), known)
        if cp not in protected and cp not in emphasis
    )
    return AiAnalysis(
        summary=summary.strip()[:_MAX_SUMMARY_CHARS] if isinstance(summary, str) else "",
        focus_key=_as_cp(data.get("focus_key"), known),
        focus_pair=_as_pair(data.get("focus_pair"), known),
        rest_keys=rest,
        emphasis_keys=emphasis,
    )


_NOT_LOADED: Final = object()


class AiAnalyzer:
    """Analyzes recent session tallies and produces coaching suggestions.

    The last good analysis of each layout is kept (in memory and in `store`)
    until a newer good one replaces it, so a timeout or a restart does not
    drop the coaching. `suggestion(layout)` is what `BuildLesson` reads."""

    def __init__(
        self,
        ai_settings_repo: AiSettingsRepository,
        settings_repo: SettingsRepository,
        client_factory: ClientFactory,
        *,
        store: AiAnalysisStore | None = None,
        archive: KeystrokeArchive | None = None,
        wall_epoch: Callable[[], float] = lambda: 0.0,
    ) -> None:
        self._ai_settings_repo = ai_settings_repo
        self._settings_repo = settings_repo
        self._client_factory = client_factory
        self._store = store
        self._archive = archive
        self._wall_epoch = wall_epoch
        self._latest: dict[str, AiAnalysis | object] = {}

    def enabled(self) -> bool:
        return self._ai_settings_repo.load().enabled

    def window(self) -> int:
        return self._settings_repo.load().confidence_session_window

    def latest(self, layout: str) -> AiAnalysis | None:
        """The last good analysis of `layout`, whether or not AI is on."""
        cached = self._latest.get(layout, _NOT_LOADED)
        if cached is _NOT_LOADED:
            cached = self._load_stored(layout)
            self._latest[layout] = cached
        return cached if isinstance(cached, AiAnalysis) else None

    def _load_stored(self, layout: str) -> AiAnalysis | None:
        if self._store is None:
            return None
        try:
            return self._store.get(layout)
        except OSError:
            return None

    def suggestion(self, layout: str) -> AiAnalysis | None:
        """The analysis to steer the next `layout` lesson with, or None if
        AI is off or nothing actionable is ready."""
        if not self.enabled():
            return None
        analysis = self.latest(layout)
        return analysis if analysis is not None and analysis.actionable else None

    def forget(self) -> None:
        """Drop every kept analysis (AI was turned off)."""
        self._latest.clear()
        if self._store is not None:
            try:
                self._store.clear()
            except OSError as exc:
                logger.warning("could not clear stored AI analyses: %s", exc)

    async def analyze(self, layout: str, sessions: Sequence[SessionResult]) -> AiAnalysis:
        """Analyze `sessions` of `layout` (most recent first, already windowed
        by the caller).

        Never raises: failures come back as an `AiAnalysis` with `error` set,
        and the previous good analysis stays in effect."""
        settings = self._ai_settings_repo.load()
        if not settings.enabled:
            return AiAnalysis(layout=layout, error="AI analysis is disabled")
        course = _course_state(sessions)
        digest = _Digest(sessions, course)
        if digest.is_empty():
            return AiAnalysis(layout=layout, summary="Not enough data yet — keep practicing.")
        try:
            insights = await asyncio.to_thread(self._insights, sessions, digest.known)
            client = self._client_factory(settings)
            raw = await client.chat(
                _SYSTEM_PROMPT,
                _build_user_prompt(sessions, digest, course, insights),
                schema=RESPONSE_SCHEMA,
            )
            protected = frozenset[int]() if course.newest is None else frozenset({course.newest})
            analysis = parse_response(raw, digest.known, protected=protected)
        except Exception as exc:
            logger.warning("AI analysis failed: %s", exc)
            error = f"AI analysis unavailable ({type(exc).__name__})"
            return AiAnalysis(layout=layout, error=error)
        analysis = replace(analysis, layout=layout, created_at=self._wall_epoch())
        self._latest[layout] = analysis
        if self._store is not None:
            try:
                await asyncio.to_thread(self._store.put, analysis)
            except OSError as exc:
                logger.warning("could not store AI analysis: %s", exc)
        return analysis

    def _insights(
        self, sessions: Sequence[SessionResult], keys: frozenset[int]
    ) -> KeystrokeInsights:
        if self._archive is None:
            return KeystrokeInsights()
        try:
            streams = self._archive.load([s.session_id for s in sessions])
        except OSError:
            return KeystrokeInsights()
        return keystroke_insights(streams.values(), keys=keys)


__all__ = [
    "RESPONSE_SCHEMA",
    "AiAnalyzer",
    "ClientFactory",
    "parse_response",
]
