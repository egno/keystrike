"""Git-backed sync orchestration for opt-in backup sync.

Composes `GitClient` (raw git subprocess plumbing, in `git_client.py`) with
the merge-execution I/O helpers (in `sync_merge_io.py`) to drive init/pull/push.
"""

from __future__ import annotations

import shutil
import tomllib
from dataclasses import dataclass
from pathlib import Path

from keystrike.domain.models import SyncStatusReport
from keystrike.domain.protocols import StatsRebuilder
from keystrike.infrastructure.git_client import GitClient, GitSyncError
from keystrike.infrastructure.paths import Paths
from keystrike.infrastructure.sync_merge_io import (
    copy_file_if_exists,
    copy_layouts_missing,
    copy_layouts_to_remote,
    import_missing_sessions,
    iter_layouts_from_index,
    read_index_session_ids,
    resolve_settings_lww,
)

from .atomic_write import atomic_write_text

__all__ = [
    "GitClient",
    "GitSyncError",
    "GitSyncGateway",
    "SyncConfig",
    "copy_file_if_exists",
    "copy_layouts_missing",
    "copy_layouts_to_remote",
    "import_missing_sessions",
    "iter_layouts_from_index",
    "read_index_session_ids",
    "resolve_settings_lww",
]

_SYNC_REL_PATHS = ("settings.toml", "layouts", "sessions")

# Substrings of `git clone` stderr that indicate the remote simply doesn't
# have any content yet (fresh bare repo, not-yet-created path) rather than a
# real failure — safe to fall back to `git init` + `git remote add` for.
_CLONE_MISSING_REMOTE_MARKERS = (
    "does not exist",
    "repository not found",
    "not appear to be a git repository",
)


def _is_missing_remote_error(stderr: str) -> bool:
    lowered = stderr.lower()
    return any(marker in lowered for marker in _CLONE_MISSING_REMOTE_MARKERS)


@dataclass(frozen=True, slots=True)
class SyncConfig:
    remote_url: str


class GitSyncGateway:
    def __init__(self, paths: Paths, *, client: GitClient | None = None) -> None:
        self._paths = paths
        self._config_path = paths.sync_config_file
        self._clone_dir = paths.sync_clone_dir
        self._client = client or GitClient()

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
            self._client.clone(url, self._clone_dir)
        except GitSyncError as exc:
            if not _is_missing_remote_error(exc.stderr):
                raise
            self._clone_dir.mkdir(parents=True, exist_ok=True)
            self._client.init(self._clone_dir)
            self._client.add_remote(self._clone_dir, url)

    def _pull_remote(self) -> None:
        self._client.pull_ff_only(self._clone_dir)

    def _push_remote(self, message: str = "keystrike sync") -> bool:
        self._client.add(self._clone_dir, *_SYNC_REL_PATHS)
        if not self._client.status_porcelain(self._clone_dir).strip():
            return False
        self._client.commit(self._clone_dir, message)
        self._client.push(self._clone_dir)
        return True

    def _status_text(self) -> str:
        if not self._clone_dir.exists():
            return "clone missing"
        return self._client.status_short(self._clone_dir)

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
