"""JSONL-backed SessionRepository. One file per session (rows = keystrokes),
plus a monthly-sharded directory and a top-level index file for headers."""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Iterator
from pathlib import Path
from typing import cast

from keystrike.domain.enums import Mode, migrate_legacy_mode
from keystrike.domain.models import Keystroke, SessionResult

from .json_coerce import coerce_float, coerce_int, require_float, require_int, require_str
from .paths import Paths


def _month_dir(started_at: float) -> str:
    return dt.datetime.fromtimestamp(started_at, tz=dt.UTC).strftime("%Y-%m")


def _session_file(paths: Paths, header: SessionResult) -> Path:
    return paths.sessions_dir / _month_dir(header.started_at) / f"{header.session_id}.jsonl"


class JsonlSessionRepository:
    def __init__(self, paths: Paths) -> None:
        self._paths = paths
        # In-memory index maps session_id → header so load_keystrokes can locate
        # the file without re-reading index.jsonl. Populated by save_header and
        # by _ensure_index (called explicitly, not as an incidental read side effect).
        self._session_index: dict[str, SessionResult] = {}
        self._indexed = False

    def append_keystroke(self, session_id: str, started_at: float, k: Keystroke) -> None:
        file = self._paths.sessions_dir / _month_dir(started_at) / f"{session_id}.jsonl"
        file.parent.mkdir(parents=True, exist_ok=True)
        with file.open("a", encoding="utf-8") as fh:
            fh.write(
                json.dumps(
                    {
                        "codepoint": k.codepoint,
                        "typed": k.typed,
                        "t_ns": k.t_ns,
                        "correct": k.correct,
                    }
                )
            )
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
        yield from self._parsed_headers()
        self._indexed = True

    def _parsed_headers(self) -> Iterator[SessionResult]:
        if not self._paths.sessions_index.exists():
            return
        with self._paths.sessions_index.open("r", encoding="utf-8") as fh:
            for raw in fh:
                line = raw.strip()
                if not line:
                    continue
                try:
                    header = _header_from_dict(json.loads(line))
                except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                    # Skip a corrupt/truncated index row rather than aborting
                    # every session recorded after it.
                    continue
                self._session_index[header.session_id] = header
                yield header

    def _ensure_index(self) -> None:
        """Populate the session-id → header index from disk, once."""
        if self._indexed:
            return
        for _ in self._parsed_headers():
            pass
        self._indexed = True

    def load_keystrokes(self, session_id: str) -> Iterator[Keystroke]:
        self._ensure_index()
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
    # Built field-by-field rather than via `dataclasses.asdict(h)`: asdict
    # falls back to `copy.deepcopy` for non-dataclass/list/tuple/dict values,
    # and deepcopy cannot pickle `key_confidence`'s `mappingproxy` wrapper.
    # A shallow `dict(...)` here sidesteps that entirely.
    return {
        "schema_version": h.schema_version,
        "session_id": h.session_id,
        "started_at": h.started_at,
        "duration_ns": h.duration_ns,
        "layout": h.layout,
        "mode": str(h.mode),  # Mode is a StrEnum → str
        "lesson_alphabet": list(h.lesson_alphabet),
        "focus_key": h.focus_key,
        "total_keystrokes": h.total_keystrokes,
        "correct_keystrokes": h.correct_keystrokes,
        "words_completed": h.words_completed,
        "lang": h.lang,
        "unlocked_keys": list(h.unlocked_keys),
        "key_confidence": {str(k): v for k, v in h.key_confidence.items()},
        "target_speed_cpm": h.target_speed_cpm,
    }


def _parse_mode(raw: str) -> Mode:
    return migrate_legacy_mode(raw)


def _require_int_tuple(
    d: dict[str, object], key: str, default: tuple[int, ...] = ()
) -> tuple[int, ...]:
    raw = d.get(key, default)
    if not isinstance(raw, (list, tuple)):
        raise TypeError(f"expected list/tuple for {key!r}, got {type(raw).__name__}: {raw!r}")
    items = cast("list[object] | tuple[object, ...]", raw)
    return tuple(coerce_int(v, label=f"{key} element") for v in items)


def _parse_key_confidence(raw: object) -> dict[int, float]:
    if not isinstance(raw, dict):
        return {}
    out: dict[int, float] = {}
    mapping = cast("dict[object, object]", raw)
    for k, v in mapping.items():
        out[coerce_int(k, label="key_confidence key")] = coerce_float(
            v, label="key_confidence value"
        )
    return out


def _header_from_dict(d: dict[str, object]) -> SessionResult:
    return SessionResult(
        schema_version=require_int(d, "schema_version"),
        session_id=require_str(d, "session_id"),
        started_at=require_float(d, "started_at"),
        duration_ns=require_int(d, "duration_ns"),
        layout=require_str(d, "layout"),
        mode=_parse_mode(require_str(d, "mode")),
        lesson_alphabet=_require_int_tuple(d, "lesson_alphabet"),
        focus_key=require_int(d, "focus_key") if d.get("focus_key") is not None else None,
        total_keystrokes=require_int(d, "total_keystrokes"),
        correct_keystrokes=require_int(d, "correct_keystrokes"),
        words_completed=require_int(d, "words_completed", 0),
        lang=require_str(d, "lang", "en"),
        unlocked_keys=_require_int_tuple(d, "unlocked_keys"),
        key_confidence=_parse_key_confidence(d.get("key_confidence", {})),
        target_speed_cpm=require_int(d, "target_speed_cpm", 0),
    )
