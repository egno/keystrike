"""File-backed AggregatesCache. Stores per-layout key stats as JSON so a
Stats-screen open doesn't require replaying every keystroke from disk."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from keystrike.domain.aggregate import without_same_key_transitions
from keystrike.domain.models import Bigram, KeyStats, LayoutAggregates, TransitionStats

from .atomic_write import atomic_write_text
from .json_coerce import require_float, require_int
from .paths import Paths


def _coerce_samples(entry: dict[str, object]) -> int:
    samples = require_int(entry, "samples")
    if samples <= 0 and require_float(entry, "mean_time_ns") > 0:
        return 1
    return samples


def _coerce_attempt_count(entry: dict[str, object]) -> int:
    samples = _coerce_samples(entry)
    errors = require_int(entry, "error_count")
    inferred = samples + errors
    stored = require_int(entry, "attempt_count", inferred)
    if stored <= 0 and inferred > 0:
        return inferred
    return stored


class FileAggregatesCache:
    def __init__(self, paths: Paths) -> None:
        self._paths = paths

    def _file(self, layout: str) -> Path:
        safe = layout.replace("/", "_").replace("\\", "_")
        return self._paths.cache_dir / f"aggregates-{safe}.json"

    def get(self, layout: str) -> LayoutAggregates | None:
        file = self._file(layout)
        if not file.exists():
            return None
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
            keys = data.get("keys", {})
            transitions = data.get("transitions", {})
            parsed_transitions = {
                Bigram(
                    require_int(entry, "prev_cp"),
                    require_int(entry, "next_cp"),
                ): TransitionStats(
                    prev_cp=require_int(entry, "prev_cp"),
                    next_cp=require_int(entry, "next_cp"),
                    samples=_coerce_samples(entry),
                    mean_time_ns=require_float(entry, "mean_time_ns"),
                    error_count=require_int(entry, "error_count"),
                    last_seen=require_float(entry, "last_seen"),
                    attempt_count=_coerce_attempt_count(entry),
                )
                for entry in transitions.values()
            }
            aggregates = LayoutAggregates(
                keys={
                    int(cp): KeyStats(
                        codepoint=int(cp),
                        samples=_coerce_samples(entry),
                        mean_time_ns=require_float(entry, "mean_time_ns"),
                        error_count=require_int(entry, "error_count"),
                        last_seen=require_float(entry, "last_seen"),
                        attempt_count=_coerce_attempt_count(entry),
                    )
                    for cp, entry in keys.items()
                },
                transitions=without_same_key_transitions(parsed_transitions),
            )
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            return None
        return aggregates

    def put(self, layout: str, aggregates: LayoutAggregates) -> None:
        transitions = without_same_key_transitions(aggregates.transitions)
        payload = {
            "schema_version": 1,
            "layout": layout,
            "keys": {str(cp): asdict(k) for cp, k in aggregates.keys.items()},
            "transitions": {key.chars(): asdict(t) for key, t in transitions.items()},
        }
        atomic_write_text(self._file(layout), json.dumps(payload, indent=2))
