"""The prompt and the reply parser of the LLM advisor.

The model answers with plain characters; this module maps them onto
codepoints and drops anything that is not a key it was shown. The core
validates the result again (`validate_advice`), so a hallucinated reply can
never steer a lesson at a locked key."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any, Final, cast

from keystrike.plugin_api import (
    AdvisorContext,
    Bigram,
    CourseState,
    Evidence,
    Finger,
    Hand,
    KeystrokeInsights,
    KeyTally,
    KeyTiming,
    Kind,
    LessonAdvice,
    Reason,
    Recommendation,
    error_rate_ranked,
    format_char,
)

MAX_SUMMARY_CHARS: Final = 200
MAX_KEY_LIST: Final = 5
PROMPT_TOP_KEYS: Final = 8
PROMPT_TOP_PAIRS: Final = 5
_PAIR_LEN = 2

SYSTEM_PROMPT: Final = (
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
_KEY_LIST: Final = {"type": "array", "items": {"type": "string"}, "maxItems": MAX_KEY_LIST}
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

_FINGER_NAMES: Final = {
    Finger.PINKY: "pinky",
    Finger.RING: "ring finger",
    Finger.MIDDLE: "middle finger",
    Finger.INDEX: "index finger",
    Finger.THUMB: "thumb",
}
_HAND_NAMES: Final = {Hand.L: "left", Hand.R: "right"}


def _mean_ms(t: KeyTally) -> float:
    return t.time_ns / t.samples / 1e6 if t.samples else 0.0


def _course_lines(course: CourseState) -> list[str]:
    lines: list[str] = []
    if course.target_cpm > 0:
        target_ms = 60_000.0 / course.target_cpm
        lines.append(f"Goal: {course.target_cpm} CPM ({target_ms:.0f} ms per key).")
    if course.unlocked:
        lines.append(
            "Unlocked keys, in learning order: " + " ".join(chr(cp) for cp in course.unlocked)
        )
    if course.newest is not None:
        lines.append(f"Newest key (being learned now): {chr(course.newest)}")
    return lines


def _key_lines(ctx: AdvisorContext) -> list[str]:
    lines = ["Keys, worst first (error rate, mean time per key, confidence 0-1, 1 = mastered):"]
    for cp, t in error_rate_ranked(ctx.digest.keys)[:PROMPT_TOP_KEYS]:
        rate = t.errors / t.attempts if t.attempts else 0.0
        line = f"- '{chr(cp)}': {rate:.0%} errors ({t.errors}/{t.attempts}), {_mean_ms(t):.0f} ms"
        if cp in ctx.course.confidence:
            line += f", confidence {ctx.course.confidence[cp]:.2f}"
        lines.append(line)
    return lines


def _pair_lines(ctx: AdvisorContext) -> list[str]:
    def rate(t: KeyTally) -> float:
        return t.errors / (t.attempts + 3)

    worst = sorted(ctx.digest.pairs.items(), key=lambda kv: -rate(kv[1]))
    worst = [(p, t) for p, t in worst if t.errors > 0][:PROMPT_TOP_PAIRS]
    if not worst:
        return []
    return ["Key pairs with errors:"] + [
        f"- '{chr(p.prev_cp)}{chr(p.next_cp)}': {t.errors} errors / {t.attempts} attempts"
        for p, t in worst
    ]


def _insight_lines(insights: KeystrokeInsights) -> list[str]:
    lines: list[str] = []
    if insights.confusions:
        lines.append("Common mistypes (target typed as):")
        lines.extend(
            f"- '{chr(c.target)}' typed as '{chr(c.typed)}': {c.count} times"
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


def build_user_prompt(ctx: AdvisorContext) -> str:
    lines = _course_lines(ctx.course)
    lines.append(f"Last {len(ctx.sessions)} session(s), latest first:")
    for i, s in enumerate(ctx.sessions, 1):
        accuracy = s.correct_keystrokes / s.total_keystrokes if s.total_keystrokes else 0.0
        lines.append(f"- session {i}: {s.cpm:.0f} CPM, {accuracy:.0%} accuracy")
    lines.append(
        f"The key tallies cover {ctx.coverage.digest_sessions} session(s); the mistype and "
        f"finger data covers {ctx.coverage.stream_sessions}."
    )
    lines.extend(_timing_lines(ctx))
    lines.extend(_key_lines(ctx))
    lines.extend(_pair_lines(ctx))
    lines.extend(_insight_lines(ctx.insights))
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
    return tuple(out[:MAX_KEY_LIST])


def _as_pair(value: Any, known: frozenset[int]) -> Bigram | None:
    chars: Sequence[Any]
    if isinstance(value, str) and len(value) == _PAIR_LEN:
        chars = list(value)
    elif isinstance(value, list) and len(cast("list[Any]", value)) == _PAIR_LEN:
        chars = cast("list[Any]", value)
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


EMPHASIS_STRENGTH: Final = 0.7
FOCUS_STRENGTH: Final = 0.8
EASE_STRENGTH: Final = 0.5
SLOW_MARGIN: Final = 1.05
MIN_SPEED_PRESSES: Final = 20
MIN_SPEED_SESSIONS: Final = 2


def _evidence(t: KeyTally | None, sessions: int, *, successes: bool = False) -> Evidence:
    """A key's own exact counts: its errors, or (for easing) its correct presses."""
    if t is None:
        return Evidence(0, 0, sessions)
    return Evidence(t.samples if successes else t.errors, t.attempts, sessions)


def _slow_timing(ctx: AdvisorContext, cp: int) -> KeyTiming | None:
    """The key's timing when it is clearly slower than the goal, judged on
    the recency-weighted median of clean presses (not on the mean, which a few
    long pauses pull up). None when the key is not slow or has too little data."""
    timing = ctx.digest.timing.get(cp)
    goal = ctx.course.goal_ms
    if timing is None or goal <= 0:
        return None
    enough = timing.presses >= MIN_SPEED_PRESSES and timing.sessions >= MIN_SPEED_SESSIONS
    return timing if enough and timing.recent_median_ms > goal * SLOW_MARGIN else None


def _timing_lines(ctx: AdvisorContext) -> list[str]:
    """Speed per key from clean presses: the median, and how many ran over the goal."""
    goal = ctx.course.goal_ms
    if not ctx.digest.timing or goal <= 0:
        return []
    ranked = sorted(ctx.digest.timing.items(), key=lambda kv: -kv[1].recent_median_ms)
    lines = [
        f"Speed per key (median of clean presses; goal {goal:.0f} ms; "
        "presses after a space and corrections are left out):"
    ]
    lines.extend(
        f"- '{chr(cp)}': median {t.recent_median_ms:.0f} ms, "
        f"{t.over_goal} of {t.presses} over the goal"
        for cp, t in ranked[:PROMPT_TOP_KEYS]
    )
    return lines


def parse_response(text: str, ctx: AdvisorContext) -> LessonAdvice:
    """Parse a model reply into recommendations, one key each. The model
    gives characters; the evidence of each key comes from the context's
    digest, not from the model. The model's summary text is kept. Invalid
    fields are dropped; a reply that is not a JSON object raises `ValueError`."""
    parsed = _extract_json_object(text)
    if not isinstance(parsed, dict):
        raise ValueError("reply is not a JSON object")
    data = cast("dict[str, Any]", parsed)
    known = frozenset(ctx.digest.keys)
    sessions = ctx.coverage.digest_sessions
    summary: Any = data.get("summary")
    recs: list[Recommendation] = []
    focus_pair = _as_pair(data.get("focus_pair"), known)
    if focus_pair is not None:
        recs.append(
            Recommendation(
                Kind.FOCUS_PAIR,
                (focus_pair.prev_cp, focus_pair.next_cp),
                Reason.ACCURACY,
                strength=FOCUS_STRENGTH,
                evidence=_evidence(ctx.digest.pairs.get(focus_pair), sessions),
            )
        )
    focus_key = _as_cp(data.get("focus_key"), known)
    if focus_key is not None:
        recs.append(
            Recommendation(
                Kind.FOCUS,
                (focus_key,),
                Reason.ACCURACY,
                strength=FOCUS_STRENGTH,
                evidence=_evidence(ctx.digest.keys.get(focus_key), sessions),
            )
        )
    for cp in _as_cp_list(data.get("emphasis_keys"), known):
        slow = _slow_timing(ctx, cp)
        recs.append(
            Recommendation(
                Kind.EMPHASIZE,
                (cp,),
                Reason.SPEED if slow is not None else Reason.ACCURACY,
                strength=EMPHASIS_STRENGTH,
                evidence=(
                    Evidence(slow.over_goal, slow.presses, slow.sessions)
                    if slow is not None
                    else _evidence(ctx.digest.keys[cp], sessions)
                ),
            )
        )
    recs.extend(
        Recommendation(
            Kind.EASE,
            (cp,),
            Reason.MASTERED,
            strength=EASE_STRENGTH,
            evidence=_evidence(ctx.digest.keys[cp], sessions, successes=True),
        )
        for cp in _as_cp_list(data.get("rest_keys"), known)
    )
    return LessonAdvice(
        summary=summary.strip()[:MAX_SUMMARY_CHARS] if isinstance(summary, str) else "",
        recommendations=tuple(recs),
    )


__all__ = [
    "RESPONSE_SCHEMA",
    "SYSTEM_PROMPT",
    "build_user_prompt",
    "format_char",
    "parse_response",
]
