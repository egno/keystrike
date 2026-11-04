from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

from keystrike.domain.enums import Finger
from keystrike.domain.models import Keystroke
from keystrike.infrastructure.atomic_write import atomic_write_text


def _finger_from_name(name: object) -> Finger | None:
    if isinstance(name, str):
        return Finger.__members__.get(name)
    return None


class RawKeystrokeStore:
    """Per-session raw keystroke archive as JSONL, one file per session.

    Lives outside `sessions/` on purpose: that directory is git-synced, and
    raw keystrokes must stay local."""

    def __init__(self, directory: Path) -> None:
        self._dir = directory

    def _path(self, session_id: str) -> Path:
        return self._dir / f"{session_id}.jsonl"

    def save(self, session_id: str, keystrokes: Sequence[Keystroke]) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        lines = [
            json.dumps(
                {
                    "target": ks.codepoint,
                    "typed": ks.typed,
                    "t_ns": ks.t_ns,
                    "correct": ks.correct,
                    "finger": ks.finger.name if ks.finger is not None else None,
                }
            )
            for ks in keystrokes
        ]
        atomic_write_text(self._path(session_id), "\n".join(lines) + ("\n" if lines else ""))

    def load(self, session_ids: Sequence[str]) -> dict[str, list[Keystroke]]:
        result: dict[str, list[Keystroke]] = {}
        for sid in session_ids:
            path = self._path(sid)
            if not path.exists():
                continue
            keystrokes: list[Keystroke] = []
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    rec = json.loads(line)
                    keystrokes.append(
                        Keystroke(
                            codepoint=int(rec["target"]),
                            typed=int(rec["typed"]),
                            t_ns=int(rec["t_ns"]),
                            correct=bool(rec["correct"]),
                            finger=_finger_from_name(rec.get("finger")),
                        )
                    )
                except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                    continue  # skip a corrupt row, keep the rest
            result[sid] = keystrokes
        return result
