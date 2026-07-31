"""Pure merge-decision rules for git-backed sync (sessions union, settings LWW).

Everything here takes already-loaded data — parsed index entries, filename
sets, timestamps, file contents as text — and returns a description of what
should happen (which sessions to import, which settings file wins, which
layout files are missing). No `Path`/`shutil`/disk I/O of any kind happens in
this module. `infrastructure/sync_git.py` reads the real inputs off disk,
calls the functions below to decide what to do, and performs the actual copy/
write operations against the resulting plan.
"""

from __future__ import annotations

import datetime as dt
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

# Crockford base32 alphabet used in ULID generation (from infrastructure/id_gen.py)
_ULID_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_ULID_LENGTH = 26


def validate_session_id(session_id: str) -> None:
    """Validate that session_id is a properly-formatted ULID.

    ULIDs are 26 characters of Crockford base32 (no path separators, no `.`,
    no `..` sequences that could enable path traversal). Rejects malformed
    session_ids at the domain layer so they don't reach filesystem operations.
    """
    if len(session_id) != _ULID_LENGTH:
        raise ValueError(f"session_id must be {_ULID_LENGTH} characters, got {len(session_id)}")
    if not all(c in _ULID_ALPHABET for c in session_id):
        raise ValueError(f"session_id contains invalid characters; only {_ULID_ALPHABET!r} allowed")


@dataclass(frozen=True, slots=True)
class SessionIndexEntry:
    """One parsed row of a sessions index file (`session_id`/`layout`/`started_at`)."""

    session_id: str
    layout: str
    started_at: float

    @classmethod
    def from_dict(cls, raw: Mapping[str, object]) -> SessionIndexEntry:
        started_at = raw["started_at"]
        if not isinstance(started_at, (int, float)):
            raise TypeError(f"expected numeric 'started_at', got {type(started_at).__name__}")
        session_id = str(raw["session_id"])
        validate_session_id(session_id)
        return cls(
            session_id=session_id,
            layout=str(raw["layout"]),
            started_at=float(started_at),
        )


def index_session_ids(entries: Sequence[SessionIndexEntry]) -> set[str]:
    """Session ids present in a parsed sessions index."""
    return {entry.session_id for entry in entries}


def index_layouts(entries: Sequence[SessionIndexEntry]) -> set[str]:
    """Distinct layout names referenced by a parsed sessions index."""
    return {entry.layout for entry in entries}


@dataclass(frozen=True, slots=True)
class SessionImportPlan:
    """One remote session that should be imported locally."""

    session_id: str
    month: str
    filename: str
    index_line: str


def plan_missing_sessions(
    *,
    local_session_ids: set[str],
    remote_entries: Sequence[SessionIndexEntry],
    remote_lines: list[str],
) -> list[SessionImportPlan]:
    """Decide which remote sessions are missing locally and need importing.

    `remote_entries`/`remote_lines` are the parsed and matching raw (stripped)
    text of each line in the remote index, in file order. This does not check
    whether the session's `.jsonl` file actually exists on disk — the
    infrastructure executor skips any plan entry whose source file is missing.
    """
    seen = set(local_session_ids)
    plans: list[SessionImportPlan] = []
    for entry, line in zip(remote_entries, remote_lines, strict=True):
        session_id = entry.session_id
        if session_id in seen:
            continue
        started_at = entry.started_at
        month = dt.datetime.fromtimestamp(started_at, tz=dt.UTC).strftime("%Y-%m")
        plans.append(
            SessionImportPlan(
                session_id=session_id,
                month=month,
                filename=f"{session_id}.jsonl",
                index_line=line,
            ),
        )
        seen.add(session_id)
    return plans


def settings_epoch_from_toml(raw: str, mtime: float) -> float:
    """Effective LWW timestamp for settings TOML text already read from disk.

    Parsing TOML text is pure (`tomllib.loads` operates on a string, not a
    file). `mtime` is the caller-supplied `st_mtime` fallback used when the
    document has no `updated_at` field.
    """
    data = tomllib.loads(raw)
    updated = data.get("updated_at")
    if updated is not None:
        text = str(updated).replace("Z", "+00:00")
        parsed = dt.datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.UTC)
        return parsed.timestamp()
    return mtime


def decide_settings_winner(
    *,
    local_exists: bool,
    remote_exists: bool,
    local_epoch: float,
    remote_epoch: float,
) -> Literal["local", "remote", "none"]:
    """Which settings file should win: `'local'`, `'remote'`, or `'none'`.

    Callers copy the winning file over the loser: when the result is
    `'remote'`, remote always exists (copy remote -> local); when it's
    `'local'`, propagate local -> remote only if a remote file existed to
    overwrite in the first place.
    """
    if not local_exists and not remote_exists:
        return "none"
    if not remote_exists:
        return "local"
    if not local_exists:
        return "remote"
    return "local" if local_epoch >= remote_epoch else "remote"


def plan_layouts_to_copy(*, source_names: set[str], dest_names: set[str]) -> set[str]:
    """Layout TOML filenames present in source but missing from dest."""
    return source_names - dest_names
