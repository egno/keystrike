"""Filesystem I/O for merging synced state (session files, settings, layouts).

`domain/sync_merge.py` only decides *what* to do given already-loaded data.
Each function below reads inputs off disk, calls the matching pure domain
function, and performs the resulting copy/write plan.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from keystrike.domain.sync_merge import (
    SessionIndexEntry,
    decide_settings_winner,
    index_layouts,
    index_session_ids,
    plan_layouts_to_copy,
    plan_missing_sessions,
    settings_epoch_from_toml,
)


def _read_index(path: Path) -> tuple[list[SessionIndexEntry], list[str]]:
    """Load a sessions index file into parsed entries + matching raw lines.

    Corrupt/truncated rows are skipped rather than aborting the whole sync.
    """
    if not path.is_file():
        return [], []
    entries: list[SessionIndexEntry] = []
    lines: list[str] = []
    with path.open(encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line:
                continue
            try:
                entry = SessionIndexEntry.from_dict(json.loads(line))
            except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                continue
            entries.append(entry)
            lines.append(line)
    return entries, lines


def read_index_session_ids(index_path: Path) -> set[str]:
    entries, _ = _read_index(index_path)
    return index_session_ids(entries)


def iter_layouts_from_index(index_path: Path) -> set[str]:
    entries, _ = _read_index(index_path)
    return index_layouts(entries)


def import_missing_sessions(
    *,
    local_sessions_dir: Path,
    remote_sessions_dir: Path,
    local_index: Path,
    remote_index: Path,
) -> list[str]:
    """Copy session files and append index entries present remotely but not locally."""
    local_entries, _ = _read_index(local_index)
    remote_entries, remote_lines = _read_index(remote_index)
    plans = plan_missing_sessions(
        local_session_ids=index_session_ids(local_entries),
        remote_entries=remote_entries,
        remote_lines=remote_lines,
    )
    if not plans:
        return []
    local_sessions_dir.mkdir(parents=True, exist_ok=True)
    imported: list[str] = []
    for plan in plans:
        remote_file = remote_sessions_dir / plan.month / plan.filename
        if not remote_file.is_file():
            continue
        dest_dir = local_sessions_dir / plan.month
        dest_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(remote_file, dest_dir / plan.filename)
        with local_index.open("a", encoding="utf-8") as out:
            out.write(plan.index_line)
            out.write("\n")
        imported.append(plan.session_id)
    return imported


def _settings_epoch(path: Path) -> float:
    return settings_epoch_from_toml(path.read_text(encoding="utf-8"), path.stat().st_mtime)


def resolve_settings_lww(*, local_path: Path, remote_path: Path) -> str:
    """Copy the newer settings file to both sides. Returns 'local', 'remote', or 'none'."""
    local_exists = local_path.is_file()
    remote_exists = remote_path.is_file()
    winner = decide_settings_winner(
        local_exists=local_exists,
        remote_exists=remote_exists,
        local_epoch=_settings_epoch(local_path) if local_exists else 0.0,
        remote_epoch=_settings_epoch(remote_path) if remote_exists else 0.0,
    )
    if winner == "remote":
        local_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(remote_path, local_path)
    elif winner == "local" and remote_exists:
        remote_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(local_path, remote_path)
    return winner


def copy_layouts_missing(*, local_layouts: Path, remote_layouts: Path) -> int:
    """Copy remote layout TOML files missing locally."""
    if not remote_layouts.is_dir():
        return 0
    remote_names = {p.name for p in remote_layouts.glob("*.toml")}
    local_names: set[str] = (
        {p.name for p in local_layouts.glob("*.toml")} if local_layouts.is_dir() else set()
    )
    missing = plan_layouts_to_copy(source_names=remote_names, dest_names=local_names)
    if missing:
        local_layouts.mkdir(parents=True, exist_ok=True)
        for name in missing:
            shutil.copy2(remote_layouts / name, local_layouts / name)
    return len(missing)


def copy_layouts_to_remote(*, local_layouts: Path, remote_layouts: Path) -> None:
    if not local_layouts.is_dir():
        return
    remote_layouts.mkdir(parents=True, exist_ok=True)
    for src in local_layouts.glob("*.toml"):
        shutil.copy2(src, remote_layouts / src.name)


def copy_file_if_exists(src: Path, dest: Path) -> bool:
    if not src.is_file():
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    return True
