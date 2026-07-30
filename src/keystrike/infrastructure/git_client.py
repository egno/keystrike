"""Thin subprocess wrapper around the `git` CLI.

Isolates raw process plumbing so `GitSyncGateway`'s merge/sync orchestration
(in `sync_git.py`) can be unit-tested against a fake client instead of
shelling out to real git.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Protocol

# Network-bound git ops (clone/pull/push) can otherwise hang indefinitely
# waiting on credentials, freezing the whole TUI.
_GIT_TIMEOUT_S = 30


class GitSyncError(RuntimeError):
    """Raised when a git subprocess used for backup sync fails to run —
    it hung past the timeout, the `git` binary isn't installed, or the
    command itself exited non-zero (auth failure, network error, ...)."""

    def __init__(self, message: str, *, stderr: str = "") -> None:
        super().__init__(message)
        self.stderr = stderr


class GitRunner(Protocol):
    """Shape of `GitClient` as consumed by `GitSyncGateway` — an infra-internal
    seam so tests can fake git subprocess calls without subclassing `GitClient`."""

    def clone(self, url: str, dest: Path) -> None: ...
    def init(self, cwd: Path) -> None: ...
    def add_remote(self, cwd: Path, url: str) -> None: ...
    def pull_ff_only(self, cwd: Path) -> None: ...
    def add(self, cwd: Path, *paths: str) -> None: ...
    def commit(self, cwd: Path, message: str) -> None: ...
    def push(self, cwd: Path) -> None: ...
    def status_porcelain(self, cwd: Path) -> str: ...
    def status_short(self, cwd: Path) -> str: ...


class GitClient:
    """Thin subprocess wrapper around the `git` CLI.

    Isolates raw process plumbing so `GitSyncGateway`'s merge/sync
    orchestration can be unit-tested against a fake client instead of
    shelling out to real git.
    """

    def __init__(self, timeout_s: float = _GIT_TIMEOUT_S) -> None:
        self._timeout_s = timeout_s

    def run(self, *args: str, cwd: Path | None = None) -> str:
        try:
            result = subprocess.run(
                ["git", *args],
                cwd=cwd,
                check=True,
                capture_output=True,
                text=True,
                timeout=self._timeout_s,
            )
        except subprocess.TimeoutExpired as exc:
            raise GitSyncError(
                f"git {args[0]} timed out after {self._timeout_s}s "
                "(hung waiting on network/credentials?)",
            ) from exc
        except FileNotFoundError as exc:
            raise GitSyncError("git executable not found — is git installed?") from exc
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or "").strip()
            raise GitSyncError(f"git {args[0]} failed: {stderr or exc}", stderr=stderr) from exc
        return result.stdout

    def clone(self, url: str, dest: Path) -> None:
        self.run("clone", "--", url, str(dest))

    def init(self, cwd: Path) -> None:
        self.run("init", cwd=cwd)

    def add_remote(self, cwd: Path, url: str) -> None:
        self.run("remote", "add", "origin", "--", url, cwd=cwd)

    def pull_ff_only(self, cwd: Path) -> None:
        self.run("pull", "--ff-only", cwd=cwd)

    def add(self, cwd: Path, *paths: str) -> None:
        self.run("add", "--", *paths, cwd=cwd)

    def commit(self, cwd: Path, message: str) -> None:
        self.run("commit", "-m", message, cwd=cwd)

    def push(self, cwd: Path) -> None:
        self.run("push", cwd=cwd)

    def status_porcelain(self, cwd: Path) -> str:
        return self.run("status", "--porcelain", cwd=cwd)

    def status_short(self, cwd: Path) -> str:
        return self.run("status", "--short", cwd=cwd)
