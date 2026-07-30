import json
import os
import time
from pathlib import Path

import pytest

from keystrike.infrastructure.paths import Paths
from keystrike.infrastructure.sync_git import (
    GitClient,
    GitSyncError,
    GitSyncGateway,
    copy_file_if_exists,
    copy_layouts_missing,
    copy_layouts_to_remote,
    import_missing_sessions,
    iter_layouts_from_index,
    read_index_session_ids,
    resolve_settings_lww,
)


@pytest.fixture
def tree(tmp_path: Path) -> dict[str, Path]:
    local = tmp_path / "local"
    remote = tmp_path / "remote"
    local_sessions = local / "sessions"
    remote_sessions = remote / "sessions"
    for d in (local, remote, local_sessions, remote_sessions):
        d.mkdir(parents=True)
    return {
        "local": local,
        "remote": remote,
        "local_settings": local / "settings.toml",
        "remote_settings": remote / "settings.toml",
        "local_layouts": local / "layouts",
        "remote_layouts": remote / "layouts",
        "local_sessions": local_sessions,
        "remote_sessions": remote_sessions,
        "local_index": local_sessions / "index.jsonl",
        "remote_index": remote_sessions / "index.jsonl",
    }


def _write_index(path: Path, *entries: dict[str, object]) -> None:
    lines = [json.dumps(e) for e in entries]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _header(sid: str, layout: str = "qwerty") -> dict[str, object]:
    return {
        "schema_version": 1,
        "session_id": sid,
        "started_at": 1_700_000_000.0,
        "duration_ns": 1,
        "layout": layout,
        "mode": "adaptive",
        "lesson_alphabet": [97],
        "focus_key": None,
        "total_keystrokes": 1,
        "correct_keystrokes": 1,
    }


def test_read_index_session_ids_missing_file_is_empty(tree: dict[str, Path]) -> None:
    assert read_index_session_ids(tree["local_index"]) == set()


def test_read_index_session_ids_reads_existing_ids(tree: dict[str, Path]) -> None:
    _write_index(tree["local_index"], _header("A"), _header("B"))
    assert read_index_session_ids(tree["local_index"]) == {"A", "B"}


def test_iter_layouts_from_index(tree: dict[str, Path]) -> None:
    _write_index(tree["local_index"], _header("A", layout="qwerty"), _header("B", layout="dvorak"))
    assert iter_layouts_from_index(tree["local_index"]) == {"qwerty", "dvorak"}


def test_session_union_imports_missing_remote_only(tree: dict[str, Path]) -> None:
    _write_index(tree["local_index"], _header("A"))
    _write_index(tree["remote_index"], _header("A"), _header("B"))
    month = "2023-11"
    (tree["remote_sessions"] / month).mkdir()
    (tree["remote_sessions"] / month / "B.jsonl").write_text(
        '{"codepoint": 97, "typed": 97, "t_ns": 0, "correct": true}\n',
        encoding="utf-8",
    )

    imported = import_missing_sessions(
        local_sessions_dir=tree["local_sessions"],
        remote_sessions_dir=tree["remote_sessions"],
        local_index=tree["local_index"],
        remote_index=tree["remote_index"],
    )

    assert imported == ["B"]
    assert read_index_session_ids(tree["local_index"]) == {"A", "B"}
    assert (tree["local_sessions"] / month / "B.jsonl").exists()


def test_session_union_skips_duplicate_local_ids(tree: dict[str, Path]) -> None:
    _write_index(tree["local_index"], _header("A"))
    _write_index(tree["remote_index"], _header("A"), _header("B"))
    month = "2023-11"
    (tree["remote_sessions"] / month).mkdir()
    (tree["remote_sessions"] / month / "B.jsonl").write_text("{}\n", encoding="utf-8")

    import_missing_sessions(
        local_sessions_dir=tree["local_sessions"],
        remote_sessions_dir=tree["remote_sessions"],
        local_index=tree["local_index"],
        remote_index=tree["remote_index"],
    )

    lines = tree["local_index"].read_text().splitlines()
    assert lines.count(json.dumps(_header("A"))) == 1
    assert json.dumps(_header("B")) in lines


def test_session_union_skips_entries_whose_file_is_missing(tree: dict[str, Path]) -> None:
    _write_index(tree["remote_index"], _header("B"))
    # No B.jsonl on disk anywhere.

    imported = import_missing_sessions(
        local_sessions_dir=tree["local_sessions"],
        remote_sessions_dir=tree["remote_sessions"],
        local_index=tree["local_index"],
        remote_index=tree["remote_index"],
    )

    assert imported == []


def test_session_union_no_remote_index_is_noop(tree: dict[str, Path]) -> None:
    imported = import_missing_sessions(
        local_sessions_dir=tree["local_sessions"],
        remote_sessions_dir=tree["remote_sessions"],
        local_index=tree["local_index"],
        remote_index=tree["remote_index"],
    )
    assert imported == []


def test_settings_lww_prefers_updated_at(tree: dict[str, Path]) -> None:
    tree["local_settings"].write_text(
        'layout = "qwerty"\nupdated_at = "2024-01-01T00:00:00+00:00"\n',
        encoding="utf-8",
    )
    tree["remote_settings"].write_text(
        'layout = "dvorak"\nupdated_at = "2024-06-01T00:00:00+00:00"\n',
        encoding="utf-8",
    )

    winner = resolve_settings_lww(
        local_path=tree["local_settings"],
        remote_path=tree["remote_settings"],
    )

    assert winner == "remote"
    assert 'layout = "dvorak"' in tree["local_settings"].read_text()


def test_settings_lww_falls_back_to_mtime(tree: dict[str, Path]) -> None:
    tree["local_settings"].write_text('layout = "qwerty"\n', encoding="utf-8")
    tree["remote_settings"].write_text('layout = "dvorak"\n', encoding="utf-8")
    now = time.time()
    os.utime(tree["remote_settings"], (now - 100, now - 100))
    os.utime(tree["local_settings"], (now, now))

    winner = resolve_settings_lww(
        local_path=tree["local_settings"],
        remote_path=tree["remote_settings"],
    )

    assert winner == "local"
    assert tree["remote_settings"].read_text() == tree["local_settings"].read_text()


def test_settings_lww_neither_exists(tree: dict[str, Path]) -> None:
    winner = resolve_settings_lww(
        local_path=tree["local_settings"],
        remote_path=tree["remote_settings"],
    )
    assert winner == "none"
    assert not tree["local_settings"].exists()
    assert not tree["remote_settings"].exists()


def test_settings_lww_only_local_exists_does_not_touch_remote(tree: dict[str, Path]) -> None:
    tree["local_settings"].write_text('layout = "qwerty"\n', encoding="utf-8")

    winner = resolve_settings_lww(
        local_path=tree["local_settings"],
        remote_path=tree["remote_settings"],
    )

    assert winner == "local"
    assert not tree["remote_settings"].exists()


def test_settings_lww_only_remote_exists_copies_to_local(tree: dict[str, Path]) -> None:
    tree["remote_settings"].write_text('layout = "dvorak"\n', encoding="utf-8")

    winner = resolve_settings_lww(
        local_path=tree["local_settings"],
        remote_path=tree["remote_settings"],
    )

    assert winner == "remote"
    assert tree["local_settings"].read_text() == 'layout = "dvorak"\n'


def test_copy_layouts_missing_copies_only_absent_files(tree: dict[str, Path]) -> None:
    tree["remote_layouts"].mkdir()
    tree["local_layouts"].mkdir()
    (tree["remote_layouts"] / "qwerty.toml").write_text("a", encoding="utf-8")
    (tree["remote_layouts"] / "dvorak.toml").write_text("b", encoding="utf-8")
    (tree["local_layouts"] / "qwerty.toml").write_text("existing", encoding="utf-8")

    copied = copy_layouts_missing(
        local_layouts=tree["local_layouts"],
        remote_layouts=tree["remote_layouts"],
    )

    assert copied == 1
    assert (tree["local_layouts"] / "dvorak.toml").read_text() == "b"
    assert (tree["local_layouts"] / "qwerty.toml").read_text() == "existing"


def test_copy_layouts_missing_no_remote_dir(tree: dict[str, Path]) -> None:
    assert (
        copy_layouts_missing(
            local_layouts=tree["local_layouts"],
            remote_layouts=tree["remote_layouts"],
        )
        == 0
    )


def test_copy_layouts_to_remote_copies_everything(tree: dict[str, Path]) -> None:
    tree["local_layouts"].mkdir()
    (tree["local_layouts"] / "qwerty.toml").write_text("a", encoding="utf-8")

    copy_layouts_to_remote(
        local_layouts=tree["local_layouts"],
        remote_layouts=tree["remote_layouts"],
    )

    assert (tree["remote_layouts"] / "qwerty.toml").read_text() == "a"


def test_copy_layouts_to_remote_no_local_dir_is_noop(tree: dict[str, Path]) -> None:
    copy_layouts_to_remote(
        local_layouts=tree["local_layouts"],
        remote_layouts=tree["remote_layouts"],
    )
    assert not tree["remote_layouts"].exists()


def test_copy_file_if_exists_true_when_present(tree: dict[str, Path]) -> None:
    src = tree["local"] / "settings.toml"
    src.write_text("data", encoding="utf-8")
    dest = tree["remote"] / "nested" / "settings.toml"

    assert copy_file_if_exists(src, dest) is True
    assert dest.read_text() == "data"


def test_copy_file_if_exists_false_when_missing(tree: dict[str, Path]) -> None:
    src = tree["local"] / "missing.toml"
    dest = tree["remote"] / "settings.toml"

    assert copy_file_if_exists(src, dest) is False
    assert not dest.exists()


class _FakeGitClient:
    """Fakes the `GitRunner` seam: records calls, raises canned errors, no real git."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.clone_error: GitSyncError | None = None
        self.porcelain_status = " M settings.toml"

    def clone(self, url: str, dest: Path) -> None:
        self.calls.append(("clone", url, str(dest)))
        if self.clone_error is not None:
            raise self.clone_error

    def init(self, cwd: Path) -> None:
        self.calls.append(("init", str(cwd)))

    def add_remote(self, cwd: Path, url: str) -> None:
        self.calls.append(("add_remote", str(cwd), url))

    def pull_ff_only(self, cwd: Path) -> None:
        self.calls.append(("pull", str(cwd)))

    def add(self, cwd: Path, *paths: str) -> None:
        self.calls.append(("add", str(cwd), *paths))

    def commit(self, cwd: Path, message: str) -> None:
        self.calls.append(("commit", str(cwd), message))

    def push(self, cwd: Path) -> None:
        self.calls.append(("push", str(cwd)))

    def status_porcelain(self, cwd: Path) -> str:
        self.calls.append(("status_porcelain", str(cwd)))
        return self.porcelain_status

    def status_short(self, cwd: Path) -> str:
        self.calls.append(("status_short", str(cwd)))
        return "clean"


@pytest.fixture
def paths(tmp_path: Path) -> Paths:
    return Paths(
        config_dir=tmp_path / "config",
        data_dir=tmp_path / "data",
        log_dir=tmp_path / "log",
    )


def test_git_client_run_wraps_called_process_error(tmp_path: Path) -> None:
    client = GitClient()

    with pytest.raises(GitSyncError) as exc_info:
        client.run("this-is-not-a-real-git-command", cwd=tmp_path)

    assert exc_info.value.stderr


def test_gateway_init_falls_back_to_git_init_on_missing_remote(paths: Paths) -> None:
    client = _FakeGitClient()
    client.clone_error = GitSyncError(
        "git clone failed: repo not found",
        stderr="fatal: repository 'origin' does not exist",
    )
    gateway = GitSyncGateway(paths, client=client)

    gateway._clone("origin")

    assert ("init", str(paths.sync_clone_dir)) in client.calls
    assert ("add_remote", str(paths.sync_clone_dir), "origin") in client.calls
    assert paths.sync_clone_dir.is_dir()


def test_gateway_init_reraises_real_clone_failures(paths: Paths) -> None:
    client = _FakeGitClient()
    client.clone_error = GitSyncError(
        "git clone failed: auth denied",
        stderr="fatal: Authentication failed for 'origin'",
    )
    gateway = GitSyncGateway(paths, client=client)

    with pytest.raises(GitSyncError) as exc_info:
        gateway._clone("origin")

    assert "Authentication failed" in exc_info.value.stderr
    assert not any(call[0] == "init" for call in client.calls)


def test_gateway_clone_dir_survives_partial_clone(paths: Paths) -> None:
    # Simulates a clone that was interrupted mid-transfer, leaving the
    # destination directory partially populated before the retryable init.
    paths.sync_clone_dir.mkdir(parents=True)
    (paths.sync_clone_dir / "leftover").write_text("partial", encoding="utf-8")
    client = _FakeGitClient()
    client.clone_error = GitSyncError(
        "git clone failed: repo not found",
        stderr="fatal: repository 'origin' does not exist",
    )
    gateway = GitSyncGateway(paths, client=client)

    gateway._clone("origin")

    assert paths.sync_clone_dir.is_dir()


def test_gateway_push_propagates_git_sync_error_not_raw_subprocess_error(
    paths: Paths,
) -> None:
    class _FailingPushClient(_FakeGitClient):
        def push(self, cwd: Path) -> None:
            raise GitSyncError("git push failed: non-fast-forward", stderr="rejected")

    paths.sync_clone_dir.mkdir(parents=True)
    gateway = GitSyncGateway(paths, client=_FailingPushClient())

    with pytest.raises(GitSyncError, match="non-fast-forward"):
        gateway._push_remote()


def test_git_client_is_the_default_when_none_injected(paths: Paths) -> None:
    gateway = GitSyncGateway(paths)

    assert isinstance(gateway._client, GitClient)
