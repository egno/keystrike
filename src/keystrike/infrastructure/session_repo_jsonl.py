"""JSONL-backed SessionRepository. One file per session (rows = keystrokes),
plus a monthly-sharded directory and a top-level index file for headers."""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Iterator
from dataclasses import asdict
from pathlib import Path
from typing import cast

from keystrike.domain.enums import Mode
from keystrike.domain.models import Keystroke, SessionResult

from .paths import Paths


def _month_dir(started_at: float) -> str:
    return dt.datetime.fromtimestamp(started_at, tz=dt.UTC).strftime("%Y-%m")


def _session_file(paths: Paths, header: SessionResult) -> Path:
    return paths.sessions_dir / _month_dir(header.started_at) / f"{header.session_id}.jsonl"


class JsonlSessionRepository:
    def __init__(self, paths: Paths) -> None:
        self._paths = paths
        # An in-memory index maps session_id → header so append_keystroke can
        # locate the correct file without re-reading index.jsonl. Populated by
        # save_header and (lazily) by iter_headers.
        self._session_index: dict[str, SessionResult] = {}

    def append_keystroke(self, session_id: str, started_at: float, k: Keystroke) -> None:
        file = self._paths.sessions_dir / _month_dir(started_at) / f"{session_id}.jsonl"
        file.parent.mkdir(parents=True, exist_ok=True)
        with file.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "codepoint": k.codepoint,
                "typed": k.typed,
                "t_ns": k.t_ns,
                "correct": k.correct,
            }))
            fh.write("\n")

    def save_header(self, header: SessionResult) -> None:
        self._session_index[header.session_id] = header
        self._paths.sessions_index.parent.mkdir(parents=True, exist_ok=True)
        with self._paths.sessions_index.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(_header_to_dict(header)))
            fh.write("\n")

    def iter_headers(self, layout: str) -> Iterator[SessionResult]:
        for header in self.iter_all_headers():
            if header.layout == layout:
                yield header

    def iter_all_headers(self) -> Iterator[SessionResult]:
        if not self._paths.sessions_index.exists():
            return
        with self._paths.sessions_index.open("r", encoding="utf-8") as fh:
            for raw in fh:
                line = raw.strip()
                if not line:
                    continue
                data = json.loads(line)
                header = _header_from_dict(data)
                self._session_index[header.session_id] = header
                yield header

    def load_keystrokes(self, session_id: str) -> Iterator[Keystroke]:
        header = self._session_index.get(session_id)
        if header is None:
            # Fall back: scan all month directories for the ulid.
            for month_dir in self._paths.sessions_dir.iterdir():
                if not month_dir.is_dir():
                    continue
                candidate = month_dir / f"{session_id}.jsonl"
                if candidate.exists():
                    yield from _read_keystrokes(candidate)
                    return
            return
        file = _session_file(self._paths, header)
        if not file.exists():
            return
        yield from _read_keystrokes(file)


def _read_keystrokes(file: Path) -> Iterator[Keystroke]:
    with file.open("r", encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line:
                continue
            d = json.loads(line)
            yield Keystroke(
                codepoint=d["codepoint"],
                typed=d["typed"],
                t_ns=d["t_ns"],
                correct=d["correct"],
            )


def _header_to_dict(h: SessionResult) -> dict[str, object]:
    d = asdict(h)
    # Mode is a StrEnum → str; tuple → list for JSON.
    d["mode"] = str(h.mode)
    d["lesson_alphabet"] = list(h.lesson_alphabet)
    d["unlocked_keys"] = list(h.unlocked_keys)
    d["key_confidence"] = {str(k): v for k, v in h.key_confidence.items()}
    return d


def _as_int(v: object) -> int:
    return int(v)  # type: ignore[arg-type]


def _as_float(v: object) -> float:
    return float(v)  # type: ignore[arg-type]


_LEGACY_MODES = frozenset({"free", "code", "sample"})


def _parse_mode(raw: object) -> Mode:
    value = str(raw)
    if value in _LEGACY_MODES:
        return Mode.ADAPTIVE
    return Mode(value)


def _parse_key_confidence(raw: object) -> dict[int, float]:
    if not isinstance(raw, dict):
        return {}
    out: dict[int, float] = {}
    mapping = cast("dict[object, object]", raw)
    for k, v in mapping.items():
        out[_as_int(k)] = _as_float(v)
    return out


def _header_from_dict(d: dict[str, object]) -> SessionResult:
    return SessionResult(
        schema_version=_as_int(d["schema_version"]),
        session_id=str(d["session_id"]),
        started_at=_as_float(d["started_at"]),
        duration_ns=_as_int(d["duration_ns"]),
        layout=str(d["layout"]),
        mode=_parse_mode(d["mode"]),
        lesson_alphabet=tuple(d["lesson_alphabet"]),  # type: ignore[arg-type]
        focus_key=_as_int(d["focus_key"]) if d.get("focus_key") is not None else None,
        total_keystrokes=_as_int(d["total_keystrokes"]),
        correct_keystrokes=_as_int(d["correct_keystrokes"]),
        words_completed=_as_int(d.get("words_completed", 0)),
        lang=str(d.get("lang", "en")),
        unlocked_keys=tuple(d.get("unlocked_keys", ())),  # type: ignore[arg-type]
        key_confidence=_parse_key_confidence(d.get("key_confidence", {})),
        target_speed_cpm=_as_int(d.get("target_speed_cpm", 0)),
    )


