"""File-backed AggregatesCache. Stores per-layout key stats as JSON so a
Stats-screen open doesn't require replaying every keystroke from disk."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from keystrike.domain.aggregate import (
    infer_key_stat_attempt_count,
    infer_key_stat_samples,
    without_same_key_transitions,
)
from keystrike.domain.models import Bigram, KeyStats, LayoutAggregates, TransitionStats

from .atomic_write import atomic_write_text
from .json_coerce import require_float, require_int
from .paths import Paths, sanitize_layout_name


def _coerce_samples(entry: dict[str, object]) -> int:
    samples = require_int(entry, "samples")
    mean_time_ns = require_float(entry, "mean_time_ns")
    return infer_key_stat_samples(samples, mean_time_ns)


def _coerce_attempt_count(entry: dict[str, object], samples: int) -> int:
    errors = require_int(entry, "error_count")
    stored = require_int(entry, "attempt_count", samples + errors)
    return infer_key_stat_attempt_count(samples, errors, stored)


def _parse_transition_entry(entry: dict[str, object]) -> tuple[Bigram, TransitionStats]:
    samples = _coerce_samples(entry)
    return Bigram(
        require_int(entry, "prev_cp"),
        require_int(entry, "next_cp"),
    ), TransitionStats(
        prev_cp=require_int(entry, "prev_cp"),
        next_cp=require_int(entry, "next_cp"),
        samples=samples,
        mean_time_ns=require_float(entry, "mean_time_ns"),
        error_count=require_int(entry, "error_count"),
        last_seen=require_float(entry, "last_seen"),
        attempt_count=_coerce_attempt_count(entry, samples),
    )


def _parse_key_entry(cp: str, entry: dict[str, object]) -> KeyStats:
    samples = _coerce_samples(entry)
    return KeyStats(
        codepoint=int(cp),
        samples=samples,
        mean_time_ns=require_float(entry, "mean_time_ns"),
        error_count=require_int(entry, "error_count"),
        last_seen=require_float(entry, "last_seen"),
        attempt_count=_coerce_attempt_count(entry, samples),
    )


class FileAggregatesCache:
    def __init__(self, paths: Paths) -> None:
        self._paths = paths

    def _file(self, layout: str) -> Path:
        safe = sanitize_layout_name(layout)
        return self._paths.cache_dir / f"aggregates-{safe}.json"

    def get(self, layout: str) -> LayoutAggregates | None:
        file = self._file(layout)
        if not file.exists():
            return None
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
            keys = data.get("keys", {})
            transitions = data.get("transitions", {})
            parsed_transitions = dict(
                _parse_transition_entry(entry) for entry in transitions.values()
            )
            return LayoutAggregates(
                keys={int(cp): _parse_key_entry(cp, entry) for cp, entry in keys.items()},
                transitions=without_same_key_transitions(parsed_transitions),
                transitions_computed="transitions" in data,
            )
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            return None

    def put(self, layout: str, aggregates: LayoutAggregates) -> None:
        transitions = without_same_key_transitions(aggregates.transitions)
        payload = {
            "schema_version": 1,
            "layout": layout,
            "keys": {str(cp): asdict(k) for cp, k in aggregates.keys.items()},
            "transitions": {key.chars(): asdict(t) for key, t in transitions.items()},
        }
        atomic_write_text(self._file(layout), json.dumps(payload, indent=2))
