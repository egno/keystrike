from __future__ import annotations

import json
from collections.abc import Collection, Sequence
from pathlib import Path

from keystrike.domain.enums import Finger, Hand
from keystrike.domain.models import Keystroke
from keystrike.infrastructure.atomic_write import atomic_write_text

_SUFFIX = ".jsonl"


def _finger_from_name(name: object) -> Finger | None:
    if isinstance(name, str):
        return Finger.__members__.get(name)
    return None


def _hand_from_value(value: object) -> Hand | None:
    try:
        return Hand(value) if isinstance(value, str) else None
    except ValueError:
        return None


def _parse_line(line: str) -> Keystroke | None:
    try:
        rec = json.loads(line)
        return Keystroke(
            codepoint=int(rec["target"]),
            typed=int(rec["typed"]),
            t_ns=int(rec["t_ns"]),
            correct=bool(rec["correct"]),
            finger=_finger_from_name(rec.get("finger")),
            hand=_hand_from_value(rec.get("hand")),
        )
    except (json.JSONDecodeError, KeyError, TypeError, ValueError, AttributeError):
        return None  # skip a corrupt row, keep the rest


class RawKeystrokeStore:
    """Per-session raw keystroke archive as JSONL, one file per session.

    Lives outside `sessions/` on purpose: that directory is git-synced, and
    raw keystrokes must stay local."""

    def __init__(self, directory: Path) -> None:
        self._dir = directory

    def _path(self, session_id: str) -> Path:
        return self._dir / f"{session_id}{_SUFFIX}"

    def save(
        self,
        session_id: str,
        keystrokes: Sequence[Keystroke],
        *,
        layout: str = "",
        started_at: float = 0.0,
        ended_at: float = 0.0,
    ) -> None:
        """The first line describes the session (`session_id`, `layout`,
        wall-clock `started_at` / `ended_at` as unix epoch); keystroke lines
        follow. `t_ns` stays relative (active typing time). Readers skip the
        header line because it has no `target`."""
        self._dir.mkdir(parents=True, exist_ok=True)
        header = json.dumps(
            {
                "session_id": session_id,
                "layout": layout,
                "started_at": started_at,
                "ended_at": ended_at,
            }
        )
        lines = [header]
        lines += [
            json.dumps(
                {
                    "target": ks.codepoint,
                    "typed": ks.typed,
                    "t_ns": ks.t_ns,
                    "correct": ks.correct,
                    "finger": ks.finger.name if ks.finger is not None else None,
                    "hand": ks.hand.value if ks.hand is not None else None,
                }
            )
            for ks in keystrokes
        ]
        atomic_write_text(self._path(session_id), "\n".join(lines) + "\n")

    def load(self, session_ids: Sequence[str]) -> dict[str, list[Keystroke]]:
        result: dict[str, list[Keystroke]] = {}
        for sid in session_ids:
            path = self._path(sid)
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            parsed = (_parse_line(line) for line in text.splitlines() if line.strip())
            result[sid] = [ks for ks in parsed if ks is not None]
        return result

    def _files(self) -> list[Path]:
        if not self._dir.is_dir():
            return []
        return [p for p in self._dir.iterdir() if p.is_file() and p.suffix == _SUFFIX]

    def prune(self, keep: Collection[str]) -> None:
        keep_set = set(keep)
        for path in self._files():
            if path.stem not in keep_set:
                path.unlink(missing_ok=True)

    def clear(self) -> None:
        self.prune(())
