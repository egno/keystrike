"""JSONL-backed SessionRepository: `sessions/index.jsonl`, one row per finished
session — the header fields plus the session's per-key/per-bigram tallies
(`SessionResult.stats`). Raw keystrokes are not stored; schema ≤4 keystroke
logs are folded in once by `session_migration`."""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Iterable, Iterator
from typing import cast

from keystrike.domain.enums import Mode, migrate_legacy_mode
from keystrike.domain.models import (
    GENERATED_WORD_MAX_LEN,
    GENERATED_WORD_MIN_LEN,
    Bigram,
    KeyTally,
    SessionResult,
    SessionStats,
)
from keystrike.domain.sync_merge import validate_session_id

from .atomic_write import atomic_write_text
from .json_coerce import coerce_float, coerce_int, require_float, require_int, require_str
from .paths import Paths

# Row layout of `SessionResult.stats` (schema 5): compact positional tallies,
# `[samples, time_ns, errors, attempts]`, keyed by codepoint for keys and by
# "prev,next" codepoints for bigrams. Omitted entirely when the stats are empty.
_STATS_KEY = "stats"
_TALLY_FIELDS = 4


class JsonlSessionRepository:
    def __init__(self, paths: Paths) -> None:
        self._paths = paths

    def save_header(self, header: SessionResult) -> None:
        self._paths.sessions_index.parent.mkdir(parents=True, exist_ok=True)
        with self._paths.sessions_index.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(header_to_row(header)))
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
                try:
                    header = header_from_row(json.loads(line))
                except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                    # Skip a corrupt/truncated index row rather than aborting
                    # every session recorded after it.
                    continue
                yield header

    def replace_all_headers(self, headers: Iterable[SessionResult]) -> None:
        text = "".join(json.dumps(header_to_row(h)) + "\n" for h in headers)
        atomic_write_text(self._paths.sessions_index, text)


def _tally_to_row(t: KeyTally) -> list[int]:
    return list(t)  # NamedTuple field order is the row order


def stats_to_row(stats: SessionStats) -> dict[str, object]:
    return {
        "keys": {str(cp): _tally_to_row(t) for cp, t in stats.keys.items()},
        "pairs": {
            f"{key.prev_cp},{key.next_cp}": _tally_to_row(t) for key, t in stats.transitions.items()
        },
    }


def _tally_from_row(raw: object, *, label: str) -> KeyTally:
    if not isinstance(raw, (list, tuple)) or len(cast("list[object]", raw)) != _TALLY_FIELDS:
        raise TypeError(f"expected {_TALLY_FIELDS}-item tally for {label}, got {raw!r}")
    items = [coerce_int(v, label=label) for v in cast("list[object]", raw)]
    return KeyTally(samples=items[0], time_ns=items[1], errors=items[2], attempts=items[3])


def _bigram_from_row(raw: str) -> Bigram:
    prev_s, sep, next_s = raw.partition(",")
    if not sep:
        raise ValueError(f"expected 'prev,next' bigram key, got {raw!r}")
    return Bigram(coerce_int(prev_s, label="bigram prev"), coerce_int(next_s, label="bigram next"))


def _require_dict(data: dict[str, object], key: str) -> dict[str, object]:
    raw = data.get(key, {})
    if not isinstance(raw, dict):
        raise TypeError(f"expected object for stats.{key}, got {type(raw).__name__}")
    return cast("dict[str, object]", raw)


def stats_from_row(raw: object) -> SessionStats:
    if raw is None:
        return SessionStats()
    if not isinstance(raw, dict):
        raise TypeError(f"expected object for {_STATS_KEY!r}, got {type(raw).__name__}")
    data = cast("dict[str, object]", raw)
    keys_raw = _require_dict(data, "keys")
    pairs_raw = _require_dict(data, "pairs")
    return SessionStats(
        keys={
            coerce_int(cp, label="stats key"): _tally_from_row(t, label=f"key {cp}")
            for cp, t in keys_raw.items()
        },
        transitions={
            _bigram_from_row(pair): _tally_from_row(t, label=f"pair {pair}")
            for pair, t in pairs_raw.items()
        },
    )


def header_to_row(h: SessionResult) -> dict[str, object]:
    # A shallow field-by-field dict rather than `dataclasses.asdict(h)`:
    # asdict falls back to `copy.deepcopy` for non-dataclass/list/tuple/dict
    # values, and deepcopy cannot pickle `key_confidence`'s `mappingproxy`
    # wrapper. Reflection still derives the field *list* from SessionResult
    # (so a new plain-scalar field needs no update here); only the fields
    # below need a real JSON-safety conversion.
    base: dict[str, object] = {f.name: getattr(h, f.name) for f in dataclasses.fields(h)}
    base["mode"] = str(h.mode)  # Mode is a StrEnum → str
    base["lesson_alphabet"] = list(h.lesson_alphabet)
    base["unlocked_keys"] = list(h.unlocked_keys)
    base["key_confidence"] = {str(k): v for k, v in h.key_confidence.items()}
    if h.stats.is_empty:
        del base[_STATS_KEY]
    else:
        base[_STATS_KEY] = stats_to_row(h.stats)
    return base


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


def header_from_row(d: dict[str, object]) -> SessionResult:
    session_id = require_str(d, "session_id")
    validate_session_id(session_id)  # Reject path-traversal attempts
    return SessionResult(
        schema_version=require_int(d, "schema_version"),
        session_id=session_id,
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
        generated_min_len=require_int(d, "generated_min_len", GENERATED_WORD_MIN_LEN),
        generated_max_len=require_int(d, "generated_max_len", GENERATED_WORD_MAX_LEN),
        stats=stats_from_row(d.get(_STATS_KEY)),
    )
