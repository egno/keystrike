import json
import os
import time
from pathlib import Path

import pytest

from keystrike.domain.sync_merge import (
    import_missing_sessions,
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
        "local_settings": local / "settings.toml",
        "remote_settings": remote / "settings.toml",
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
