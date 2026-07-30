"""File-backed AggregatesCache. Stores per-layout key stats as JSON so a
Stats-screen open doesn't require replaying every keystroke from disk."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from keystrike.domain.aggregate import without_same_key_transitions
from keystrike.domain.models import KeyStats, LayoutAggregates, TransitionStats

from .atomic_write import atomic_write_text
from .paths import Paths


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
        data = json.loads(file.read_text(encoding="utf-8"))
        keys = data.get("keys", {})
        transitions = data.get("transitions", {})
        parsed_transitions = {
            key: TransitionStats(
                prev_cp=int(entry["prev_cp"]),
                next_cp=int(entry["next_cp"]),
                samples=int(entry["samples"]),
                mean_time_ns=float(entry["mean_time_ns"]),
                error_count=int(entry["error_count"]),
                last_seen=float(entry["last_seen"]),
                attempt_count=int(
                    entry.get("attempt_count", entry["samples"] + entry["error_count"]),
                ),
            )
            for key, entry in transitions.items()
        }
        return LayoutAggregates(
            keys={
                int(cp): KeyStats(
                    codepoint=int(cp),
                    samples=int(entry["samples"]),
                    mean_time_ns=float(entry["mean_time_ns"]),
                    error_count=int(entry["error_count"]),
                    last_seen=float(entry["last_seen"]),
                    attempt_count=int(
                        entry.get("attempt_count", entry["samples"] + entry["error_count"]),
                    ),
                )
                for cp, entry in keys.items()
            },
            transitions=without_same_key_transitions(parsed_transitions),
        )

    def put(self, layout: str, aggregates: LayoutAggregates) -> None:
        transitions = without_same_key_transitions(aggregates.transitions)
        payload = {
            "schema_version": 1,
            "layout": layout,
            "keys": {str(cp): asdict(k) for cp, k in aggregates.keys.items()},
            "transitions": {key: asdict(t) for key, t in transitions.items()},
        }
        atomic_write_text(self._file(layout), json.dumps(payload, indent=2))
