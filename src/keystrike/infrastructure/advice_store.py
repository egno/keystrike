"""File-backed AdviceStore: the last good advice per (layout, advisor), as
one JSON object in the cache directory: `{layout: {advisor: row}}`."""

from __future__ import annotations

import json
from typing import Any, cast

from keystrike.domain.advice import (
    NO_EVIDENCE,
    Evidence,
    Kind,
    LessonAdvice,
    Reason,
    Recommendation,
)

from .atomic_write import atomic_write_text
from .paths import Paths

# 3: no `note`; evidence may carry `event_sessions`. Rows of 1 and 2 are ignored.
ROW_VERSION = 3


def _int_or_none(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _float(value: Any) -> float:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else 0.0


def _int_tuple(value: Any) -> tuple[int, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(v for v in cast("list[Any]", value) if _int_or_none(v) is not None)


def _recommendation(row: Any) -> Recommendation | None:
    if not isinstance(row, dict):
        return None
    d = cast("dict[str, Any]", row)
    try:
        kind, reason = Kind(d.get("kind")), Reason(d.get("reason"))
    except ValueError:
        return None
    return Recommendation(
        kind=kind,
        keys=_int_tuple(d.get("keys")),
        reason=reason,
        strength=_float(d.get("strength")),
        evidence=_evidence(d.get("evidence")),
        applied=_float(d.get("applied")),
    )


def _evidence(value: Any) -> Evidence:
    """`[events, opportunities, sessions]` or `[..., event_sessions]`."""
    if not isinstance(value, list):
        return NO_EVIDENCE
    nums = [_int_or_none(v) for v in cast("list[Any]", value)]
    if len(nums) not in (3, 4) or any(n is None for n in nums[:3]):
        return NO_EVIDENCE
    events, opportunities, sessions = (n or 0 for n in nums[:3])
    event_sessions = nums[3] if len(nums) == 4 else None  # noqa: PLR2004
    return Evidence(events, opportunities, sessions, event_sessions)


def _from_row(advisor: str, row: Any) -> LessonAdvice | None:
    """A stored row, or None for a row of an older format (the next session
    replaces it)."""
    if not isinstance(row, dict):
        return None
    d = cast("dict[str, Any]", row)
    if d.get("version") != ROW_VERSION:
        return None
    summary = d.get("summary")
    recs = d.get("recommendations")
    parsed = [_recommendation(r) for r in cast("list[Any]", recs)] if isinstance(recs, list) else []
    return LessonAdvice(
        source=advisor,
        summary=summary if isinstance(summary, str) else "",
        recommendations=tuple(r for r in parsed if r is not None),
        created_at=_float(d.get("created_at")),
    )


def _to_row(advice: LessonAdvice) -> dict[str, Any]:
    return {
        "version": ROW_VERSION,
        "summary": advice.summary,
        "created_at": advice.created_at,
        "recommendations": [
            {
                "kind": r.kind.value,
                "keys": list(r.keys),
                "reason": r.reason.value,
                "strength": r.strength,
                "evidence": _evidence_row(r.evidence),
                "applied": r.applied,
            }
            for r in advice.recommendations
        ],
    }


def _evidence_row(ev: Evidence) -> list[int]:
    row = [ev.events, ev.opportunities, ev.sessions]
    return row if ev.event_sessions is None else [*row, ev.event_sessions]


class FileAdviceStore:
    def __init__(self, paths: Paths) -> None:
        self._path = paths.advice_file

    def _read_all(self) -> dict[str, Any]:
        try:
            data: Any = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return cast("dict[str, Any]", data) if isinstance(data, dict) else {}

    def get(self, layout: str, advisor: str) -> LessonAdvice | None:
        by_advisor = self._read_all().get(layout)
        if not isinstance(by_advisor, dict):
            return None
        return _from_row(advisor, cast("dict[str, Any]", by_advisor).get(advisor))

    def put(self, layout: str, advice: LessonAdvice) -> None:
        if advice.failed or not layout or not advice.source:
            return  # only good, layout- and advisor-bound advice is worth keeping
        data = self._read_all()
        by_advisor = data.get(layout)
        rows = cast("dict[str, Any]", by_advisor) if isinstance(by_advisor, dict) else {}
        rows[advice.source] = _to_row(advice)
        data[layout] = rows
        atomic_write_text(self._path, json.dumps(data, ensure_ascii=False, sort_keys=True))

    def clear(self) -> None:
        self._path.unlink(missing_ok=True)
