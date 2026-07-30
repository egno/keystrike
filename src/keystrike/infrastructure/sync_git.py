"""Git CLI adapter and merge orchestration for opt-in backup sync.

The actual filesystem I/O for merging (copying session files, settings,
layouts) lives here; `domain/sync_merge.py` only decides *what* to do given
already-loaded data. Each `*_execute`-style helper below reads inputs off
disk, calls the matching pure domain function, and performs the resulting
copy/write plan.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from keystrike.domain.models import SyncStatusReport
from keystrike.domain.protocols import StatsRebuilder
from keystrike.domain.sync_merge import (
    decide_settings_winner,
    index_layouts,
    index_session_ids,
    plan_layouts_to_copy,
    plan_missing_sessions,
    settings_epoch_from_toml,
)
from keystrike.infrastructure.paths import Paths

from .atomic_write import atomic_write_text

_SYNC_REL_PATHS = ("settings.toml", "layouts", "sessions")

# Network-bound git ops (clone/pull/push) can otherwise hang indefinitely
# waiting on credentials, freezing the whole TUI.
_GIT_TIMEOUT_S = 30


class GitSyncError(RuntimeError):
    """Raised when a git subprocess used for backup sync fails to run —
    either it hung past the timeout or the `git` binary isn't installed."""


@dataclass(frozen=True, slots=True)
class SyncConfig:
    remote_url: str


def _read_index(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """Load a sessions index file into parsed entries + matching raw lines."""
    if not path.is_file():
        return [], []
    entries: list[dict[str, Any]] = []
    lines: list[str] = []
    with path.open(encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line:
                continue
            entries.append(json.loads(line))
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


class GitSyncGateway:
    def __init__(self, paths: Paths) -> None:
        self._paths = paths
        self._config_path = paths.sync_config_file
        self._clone_dir = paths.sync_clone_dir

    @property
    def clone_settings(self) -> Path:
        return self._clone_dir / "settings.toml"

    @property
    def clone_layouts(self) -> Path:
        return self._clone_dir / "layouts"

    @property
    def clone_sessions(self) -> Path:
        return self._clone_dir / "sessions"

    @property
    def clone_sessions_index(self) -> Path:
        return self.clone_sessions / "index.jsonl"

    def is_configured(self) -> bool:
        return self._config_path.exists()

    def init(self, remote_url: str) -> None:
        self._save_config(SyncConfig(remote_url=remote_url))
        self._clone(remote_url)
        self._merge_both_ways()
        self._push_remote(message="keystrike sync init")

    def pull(self, rebuild: StatsRebuilder) -> int:
        self._require_configured()
        self._pull_remote()
        imported = self._merge_from_clone()
        self._rebuild_all_layouts(rebuild)
        return imported

    def push(self) -> bool:
        self._require_configured()
        self._merge_to_clone()
        return self._push_remote()

    def status(self) -> SyncStatusReport:
        if not self.is_configured():
            return SyncStatusReport(
                configured=False,
                remote_url=None,
                git_status="not configured",
                local_sessions=0,
                clone_sessions=0,
                only_local=0,
                only_clone=0,
            )
        config = self._load_config()
        local_ids = read_index_session_ids(self._paths.sessions_index)
        clone_ids = read_index_session_ids(self.clone_sessions_index)
        return SyncStatusReport(
            configured=True,
            remote_url=config.remote_url,
            git_status=self._status_text(),
            local_sessions=len(local_ids),
            clone_sessions=len(clone_ids),
            only_local=len(local_ids - clone_ids),
            only_clone=len(clone_ids - local_ids),
        )

    def push_remote(self, message: str = "keystrike sync") -> bool:
        return self._push_remote(message)

    def _load_config(self) -> SyncConfig:
        raw = tomllib.loads(self._config_path.read_text(encoding="utf-8"))
        return SyncConfig(remote_url=str(raw["remote_url"]))

    def _save_config(self, config: SyncConfig) -> None:
        escaped = config.remote_url.replace("\\", "\\\\").replace('"', '\\"')
        atomic_write_text(self._config_path, f'remote_url = "{escaped}"\n')

    def _clone(self, url: str) -> None:
        self._clone_dir.parent.mkdir(parents=True, exist_ok=True)
        if self._clone_dir.exists():
            shutil.rmtree(self._clone_dir)
        try:
            _git("clone", url, str(self._clone_dir))
        except subprocess.CalledProcessError:
            self._clone_dir.mkdir(parents=True)
            _git("init", cwd=self._clone_dir)
            _git("remote", "add", "origin", url, cwd=self._clone_dir)

    def _pull_remote(self) -> None:
        _git("pull", "--ff-only", cwd=self._clone_dir)

    def _push_remote(self, message: str = "keystrike sync") -> bool:
        _git("add", *_SYNC_REL_PATHS, cwd=self._clone_dir)
        if not _git("status", "--porcelain", cwd=self._clone_dir).strip():
            return False
        _git("commit", "-m", message, cwd=self._clone_dir)
        _git("push", cwd=self._clone_dir)
        return True

    def _status_text(self) -> str:
        if not self._clone_dir.exists():
            return "clone missing"
        return _git("status", "--short", cwd=self._clone_dir)

    def _require_configured(self) -> None:
        if not self.is_configured():
            raise RuntimeError(
                "sync not configured — run `keystrike sync init <repo-url>` first",
            )

    def _merge_from_clone(self) -> int:
        resolve_settings_lww(
            local_path=self._paths.settings_file,
            remote_path=self.clone_settings,
        )
        imported = import_missing_sessions(
            local_sessions_dir=self._paths.sessions_dir,
            remote_sessions_dir=self.clone_sessions,
            local_index=self._paths.sessions_index,
            remote_index=self.clone_sessions_index,
        )
        copy_layouts_missing(
            local_layouts=self._paths.layouts_dir,
            remote_layouts=self.clone_layouts,
        )
        return len(imported)

    def _merge_to_clone(self) -> None:
        resolve_settings_lww(
            local_path=self._paths.settings_file,
            remote_path=self.clone_settings,
        )
        import_missing_sessions(
            local_sessions_dir=self.clone_sessions,
            remote_sessions_dir=self._paths.sessions_dir,
            local_index=self.clone_sessions_index,
            remote_index=self._paths.sessions_index,
        )
        copy_layouts_to_remote(
            local_layouts=self._paths.layouts_dir,
            remote_layouts=self.clone_layouts,
        )
        copy_file_if_exists(self._paths.settings_file, self.clone_settings)

    def _merge_both_ways(self) -> None:
        self._merge_from_clone()
        self._merge_to_clone()

    def _rebuild_all_layouts(self, rebuild: StatsRebuilder) -> None:
        layouts = iter_layouts_from_index(self._paths.sessions_index)
        for layout in sorted(layouts):
            rebuild(layout)


def _git(*args: str, cwd: Path | None = None) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired as exc:
        raise GitSyncError(
            f"git {args[0]} timed out after {_GIT_TIMEOUT_S}s "
            "(hung waiting on network/credentials?)",
        ) from exc
    except FileNotFoundError as exc:
        raise GitSyncError("git executable not found — is git installed?") from exc
    return result.stdout
