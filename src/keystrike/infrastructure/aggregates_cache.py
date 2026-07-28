"""File-backed AggregatesCache. Stores per-layout key stats as JSON so a
Stats-screen open doesn't require replaying every keystroke from disk."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from keystrike.domain.models import KeyStats

from .atomic_write import atomic_write_text
from .paths import Paths


class FileAggregatesCache:
    def __init__(self, paths: Paths) -> None:
        self._paths = paths

    def _file(self, layout: str) -> Path:
        safe = layout.replace("/", "_").replace("\\", "_")
        return self._paths.cache_dir / f"aggregates-{safe}.json"

    def get(self, layout: str) -> dict[int, KeyStats] | None:
        file = self._file(layout)
        if not file.exists():
            return None
        data = json.loads(file.read_text(encoding="utf-8"))
        keys = data.get("keys", {})
        return {
            int(cp): KeyStats(
                codepoint=int(cp),
                samples=int(entry["samples"]),
                mean_time_ns=float(entry["mean_time_ns"]),
                error_count=int(entry["error_count"]),
                last_seen=float(entry["last_seen"]),
                peak_confidence=float(entry["peak_confidence"]),
            )
            for cp, entry in keys.items()
        }

    def put(self, layout: str, stats: dict[int, KeyStats]) -> None:
        payload = {
            "schema_version": 1,
            "layout": layout,
            "keys": {str(cp): asdict(k) for cp, k in stats.items()},
        }
        atomic_write_text(self._file(layout), json.dumps(payload, indent=2))

    def invalidate(self, layout: str) -> None:
        file = self._file(layout)
        if file.exists():
            file.unlink()
