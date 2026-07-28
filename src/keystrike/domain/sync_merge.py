"""Pure merge rules for git-backed sync (sessions union, settings LWW)."""

from __future__ import annotations

import datetime as dt
import json
import shutil
import tomllib
from pathlib import Path


def read_index_session_ids(index_path: Path) -> set[str]:
    return _index_session_ids(index_path)


def iter_layouts_from_index(index_path: Path) -> set[str]:
    if not index_path.is_file():
        return set()
    layouts: set[str] = set()
    with index_path.open(encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line:
                continue
            data = json.loads(line)
            layouts.add(str(data["layout"]))
    return layouts


def import_missing_sessions(
    *,
    local_sessions_dir: Path,
    remote_sessions_dir: Path,
    local_index: Path,
    remote_index: Path,
) -> list[str]:
    """Copy session files and append index entries present remotely but not locally."""
    before = _index_session_ids(local_index)
    if not remote_index.is_file():
        return []
    local_sessions_dir.mkdir(parents=True, exist_ok=True)
    imported: list[str] = []
    with remote_index.open(encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line:
                continue
            data = json.loads(line)
            session_id = str(data["session_id"])
            if session_id in before:
                continue
            started_at = float(data["started_at"])
            month = dt.datetime.fromtimestamp(started_at, tz=dt.UTC).strftime("%Y-%m")
            remote_file = remote_sessions_dir / month / f"{session_id}.jsonl"
            if not remote_file.is_file():
                continue
            dest_dir = local_sessions_dir / month
            dest_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(remote_file, dest_dir / remote_file.name)
            with local_index.open("a", encoding="utf-8") as out:
                out.write(line)
                out.write("\n")
            before.add(session_id)
            imported.append(session_id)
    return imported


def resolve_settings_lww(*, local_path: Path, remote_path: Path) -> str:
    """Copy the newer settings file to both sides. Returns 'local', 'remote', or 'none'."""
    if not local_path.is_file() and not remote_path.is_file():
        return "none"
    if not remote_path.is_file():
        return "local"
    if not local_path.is_file():
        local_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(remote_path, local_path)
        return "remote"

    local_epoch = settings_effective_epoch(local_path)
    remote_epoch = settings_effective_epoch(remote_path)
    if local_epoch >= remote_epoch:
        remote_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(local_path, remote_path)
        return "local"
    local_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(remote_path, local_path)
    return "remote"


def copy_layouts_missing(*, local_layouts: Path, remote_layouts: Path) -> int:
    """Copy remote layout TOML files missing locally."""
    if not remote_layouts.is_dir():
        return 0
    local_layouts.mkdir(parents=True, exist_ok=True)
    copied = 0
    for remote_file in remote_layouts.glob("*.toml"):
        local_file = local_layouts / remote_file.name
        if not local_file.is_file():
            shutil.copy2(remote_file, local_file)
            copied += 1
    return copied


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


def settings_effective_epoch(path: Path) -> float:
    if not path.is_file():
        return 0.0
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    updated = raw.get("updated_at")
    if updated is not None:
        text = str(updated).replace("Z", "+00:00")
        parsed = dt.datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.UTC)
        return parsed.timestamp()
    return path.stat().st_mtime


def merge_sessions_union(local_sessions: Path, remote_sessions: Path) -> int:
    return len(
        import_missing_sessions(
            local_sessions_dir=local_sessions,
            remote_sessions_dir=remote_sessions,
            local_index=local_sessions / "index.jsonl",
            remote_index=remote_sessions / "index.jsonl",
        ),
    )


def _index_session_ids(index_file: Path) -> set[str]:
    if not index_file.is_file():
        return set()
    ids: set[str] = set()
    with index_file.open(encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line:
                continue
            data = json.loads(line)
            ids.add(str(data["session_id"]))
    return ids
