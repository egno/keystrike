"""One-time migration of session history from schema ≤4 to schema 5.

Schema ≤4 kept every keystroke in `sessions/<YYYY-MM>/<ulid>.jsonl` next to a
bare header row in `sessions/index.jsonl`. Schema 5 folds each session's
keystrokes into per-key/per-bigram tallies stored on the index row itself
(`SessionResult.stats`), so the keystroke logs are read once here, embedded,
and deleted. Also used by git sync to upgrade legacy rows arriving from a
remote clone that still carries keystroke files.
"""

from __future__ import annotations

import datetime as dt
import json
import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import cast

from keystrike.domain.aggregate import tally_session
from keystrike.domain.models import Keystroke
from keystrike.domain.sync_merge import validate_session_id

from .atomic_write import atomic_write_text
from .json_coerce import require_float, require_int, require_str
from .paths import Paths
from .session_repo_jsonl import stats_to_row

STATS_SCHEMA_VERSION = 5


def _month_dir(started_at: float) -> str:
    return dt.datetime.fromtimestamp(started_at, tz=dt.UTC).strftime("%Y-%m")


def read_legacy_keystrokes(file: Path) -> Iterator[Keystroke]:
    with file.open("r", encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
                keystroke = Keystroke(
                    codepoint=d["codepoint"],
                    typed=d["typed"],
                    t_ns=d["t_ns"],
                    correct=d["correct"],
                )
            except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                # Skip a corrupt/truncated keystroke row (e.g. a crash mid-append)
                # rather than dropping the whole session's contribution.
                continue
            yield keystroke


def is_legacy_row(row: dict[str, object]) -> bool:
    return require_int(row, "schema_version", 0) < STATS_SCHEMA_VERSION


def embed_legacy_stats(row: dict[str, object], sessions_dir: Path) -> dict[str, object]:
    """Schema-5 copy of a legacy index row, with tallies folded in from its
    keystroke file under `sessions_dir` (empty stats when the file is gone).
    Rows already at schema 5 are returned unchanged."""
    if not is_legacy_row(row):
        return row
    session_id = require_str(row, "session_id")
    validate_session_id(session_id)  # Reject path-traversal attempts
    file = sessions_dir / _month_dir(require_float(row, "started_at")) / f"{session_id}.jsonl"
    upgraded = dict(row)
    upgraded["schema_version"] = STATS_SCHEMA_VERSION
    upgraded.pop("stats", None)
    if file.is_file():
        stats = tally_session(read_legacy_keystrokes(file))
        if not stats.is_empty:
            upgraded["stats"] = stats_to_row(stats)
    return upgraded


def upgrade_index_line(line: str, sessions_dir: Path) -> str:
    """`embed_legacy_stats` for one raw index line; unparseable lines pass through."""
    try:
        row = json.loads(line)
    except json.JSONDecodeError:
        return line
    if not isinstance(row, dict):
        return line
    try:
        return json.dumps(embed_legacy_stats(cast("dict[str, object]", row), sessions_dir))
    except (KeyError, TypeError, ValueError):
        return line


def migrate_keystroke_files(paths: Paths) -> int:
    """Upgrade every legacy index row and delete the per-session keystroke
    logs. Returns the number of rows upgraded; a no-op on an already-migrated
    store (no month directories, all rows at schema 5)."""
    sessions_dir = paths.sessions_dir
    index = paths.sessions_index
    if not sessions_dir.is_dir() or not index.is_file():
        # Without an index there is nothing to fold the logs into, so leave
        # any keystroke files alone rather than orphaning their data.
        return 0
    month_dirs = [p for p in sessions_dir.iterdir() if p.is_dir()]

    upgraded = 0
    out_lines: list[str] = []
    with index.open("r", encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line:
                continue
            new_line = upgrade_index_line(line, sessions_dir)
            if new_line != line:
                upgraded += 1
            out_lines.append(new_line)
    if upgraded:
        atomic_write_text(index, "".join(f"{line}\n" for line in out_lines))

    # Only after the index is safely rewritten: the logs are now redundant.
    for month_dir in month_dirs:
        shutil.rmtree(month_dir, ignore_errors=True)
    return upgraded
