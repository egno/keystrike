"""File-backed AiAnalysisStore: the last good AI analysis per layout, as
one JSON object keyed by layout name in the cache directory."""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any, cast

from keystrike.domain.ai_models import AiAnalysis
from keystrike.domain.models import Bigram

from .atomic_write import atomic_write_text
from .paths import Paths


def _int_or_none(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _int_tuple(value: Any) -> tuple[int, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(v for v in cast("list[Any]", value) if _int_or_none(v) is not None)


def _pair(value: Any) -> Bigram | None:
    if isinstance(value, list) and len(cast("list[Any]", value)) == 2:  # noqa: PLR2004
        first, second = (_int_or_none(v) for v in cast("list[Any]", value))
        if first is not None and second is not None:
            return Bigram(first, second)
    return None


def _from_row(layout: str, row: Any) -> AiAnalysis | None:
    if not isinstance(row, dict):
        return None
    d = cast("dict[str, Any]", row)
    summary = d.get("summary")
    created_at = d.get("created_at")
    return AiAnalysis(
        layout=layout,
        summary=summary if isinstance(summary, str) else "",
        focus_key=_int_or_none(d.get("focus_key")),
        focus_pair=_pair(d.get("focus_pair")),
        rest_keys=_int_tuple(d.get("rest_keys")),
        emphasis_keys=_int_tuple(d.get("emphasis_keys")),
        created_at=float(created_at) if isinstance(created_at, int | float) else 0.0,
    )


def _to_row(analysis: AiAnalysis) -> dict[str, Any]:
    row = asdict(analysis)
    row.pop("layout")
    row.pop("error")
    row["focus_pair"] = list(analysis.focus_pair) if analysis.focus_pair is not None else None
    row["rest_keys"] = list(analysis.rest_keys)
    row["emphasis_keys"] = list(analysis.emphasis_keys)
    return row


class FileAiAnalysisStore:
    def __init__(self, paths: Paths) -> None:
        self._path = paths.ai_analysis_file

    def _read_all(self) -> dict[str, Any]:
        try:
            data: Any = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return cast("dict[str, Any]", data) if isinstance(data, dict) else {}

    def get(self, layout: str) -> AiAnalysis | None:
        return _from_row(layout, self._read_all().get(layout))

    def put(self, analysis: AiAnalysis) -> None:
        if analysis.failed or not analysis.layout:
            return  # only good, layout-bound analyses are worth keeping
        data = self._read_all()
        data[analysis.layout] = _to_row(analysis)
        atomic_write_text(self._path, json.dumps(data, ensure_ascii=False, sort_keys=True))

    def clear(self) -> None:
        self._path.unlink(missing_ok=True)
