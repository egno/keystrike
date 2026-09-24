import json
from pathlib import Path

import pytest

from keystrike.domain.models import Bigram, KeyTally
from keystrike.infrastructure.paths import Paths
from keystrike.infrastructure.session_migration import (
    embed_legacy_stats,
    migrate_keystroke_files,
    upgrade_index_line,
)
from keystrike.infrastructure.session_repo_jsonl import JsonlSessionRepository

_VALID_ULID_A = "01ARZ3NDEKTSV4RRFFQ69G5FAV"
_VALID_ULID_B = "01ARZ3NDEKTSV4RRFFQ69G5FBV"
_STARTED_AT = 1_700_000_000.0  # 2023-11
_MONTH = "2023-11"


@pytest.fixture
def paths(tmp_path: Path) -> Paths:
    p = Paths(
        config_dir=tmp_path / "config",
        data_dir=tmp_path / "data",
        log_dir=tmp_path / "logs",
    )
    p.sessions_dir.mkdir(parents=True)
    return p


def _legacy_row(sid: str, schema_version: int = 4) -> dict[str, object]:
    return {
        "schema_version": schema_version,
        "session_id": sid,
        "started_at": _STARTED_AT,
        "duration_ns": 1_000_000_000,
        "layout": "qwerty",
        "mode": "adaptive",
        "lesson_alphabet": [97, 98],
        "focus_key": None,
        "total_keystrokes": 3,
        "correct_keystrokes": 2,
    }


def _write_keystroke_log(paths: Paths, sid: str) -> Path:
    month_dir = paths.sessions_dir / _MONTH
    month_dir.mkdir(exist_ok=True)
    file = month_dir / f"{sid}.jsonl"
    file.write_text(
        '{"codepoint": 97, "typed": 97, "t_ns": 0, "correct": true}\n'
        '{"codepoint": 98, "typed": 120, "t_ns": 50000000, "correct": false}\n'
        "{not valid json\n"
        '{"codepoint": 98, "typed": 98, "t_ns": 100000000, "correct": true}\n',
        encoding="utf-8",
    )
    return file


def _write_index(paths: Paths, *rows: dict[str, object] | str) -> None:
    lines = [r if isinstance(r, str) else json.dumps(r) for r in rows]
    paths.sessions_index.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")


def test_embed_legacy_stats_folds_keystroke_file_into_row(paths: Paths) -> None:
    _write_keystroke_log(paths, _VALID_ULID_A)

    row = embed_legacy_stats(_legacy_row(_VALID_ULID_A), paths.sessions_dir)

    assert row["schema_version"] == 5
    stats = row["stats"]
    assert isinstance(stats, dict)
    assert stats["keys"] == {"97": [0, 0, 0, 1], "98": [1, 100_000_000, 1, 2]}
    assert stats["pairs"] == {"97,98": [1, 100_000_000, 1, 2]}


def test_embed_legacy_stats_without_file_yields_no_stats(paths: Paths) -> None:
    row = embed_legacy_stats(_legacy_row(_VALID_ULID_A), paths.sessions_dir)
    assert row["schema_version"] == 5
    assert "stats" not in row


def test_embed_legacy_stats_leaves_schema_5_rows_alone(paths: Paths) -> None:
    row = _legacy_row(_VALID_ULID_A, schema_version=5)
    row["stats"] = {"keys": {"97": [1, 1, 0, 1]}, "pairs": {}}
    assert embed_legacy_stats(row, paths.sessions_dir) is row


def test_upgrade_index_line_passes_unparseable_lines_through(paths: Paths) -> None:
    assert upgrade_index_line("{not json", paths.sessions_dir) == "{not json"
    assert upgrade_index_line('{"schema_version": 1}', paths.sessions_dir) == (
        '{"schema_version": 1}'
    )
    assert upgrade_index_line("[1, 2]", paths.sessions_dir) == "[1, 2]"


def test_migrate_rewrites_rows_and_deletes_keystroke_logs(paths: Paths) -> None:
    _write_keystroke_log(paths, _VALID_ULID_A)
    _write_index(paths, _legacy_row(_VALID_ULID_A), _legacy_row(_VALID_ULID_B))

    upgraded = migrate_keystroke_files(paths)

    assert upgraded == 2
    assert not (paths.sessions_dir / _MONTH).exists()
    headers = {h.session_id: h for h in JsonlSessionRepository(paths).iter_all_headers()}
    a, b = headers[_VALID_ULID_A], headers[_VALID_ULID_B]
    assert a.schema_version == 5
    assert a.stats.keys[ord("b")] == KeyTally(1, 100_000_000, 1, 2)
    assert a.stats.transitions[Bigram(ord("a"), ord("b"))] == KeyTally(1, 100_000_000, 1, 2)
    assert b.stats.is_empty  # log was already gone: history row survives
    # Every other header field is untouched.
    assert a.total_keystrokes == 3
    assert a.lesson_alphabet == (ord("a"), ord("b"))


def test_migrate_keeps_corrupt_index_lines_verbatim(paths: Paths) -> None:
    _write_index(paths, "{not valid json", _legacy_row(_VALID_ULID_A))

    assert migrate_keystroke_files(paths) == 1
    lines = paths.sessions_index.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "{not valid json"
    assert json.loads(lines[1])["schema_version"] == 5


def test_migrate_is_a_noop_on_migrated_store(paths: Paths) -> None:
    _write_keystroke_log(paths, _VALID_ULID_A)
    _write_index(paths, _legacy_row(_VALID_ULID_A))
    migrate_keystroke_files(paths)
    before = paths.sessions_index.read_text(encoding="utf-8")

    assert migrate_keystroke_files(paths) == 0
    assert paths.sessions_index.read_text(encoding="utf-8") == before


def test_migrate_without_index_leaves_logs_untouched(paths: Paths) -> None:
    """No index means nothing to fold the keystrokes into — never delete them."""
    file = _write_keystroke_log(paths, _VALID_ULID_A)
    assert migrate_keystroke_files(paths) == 0
    assert file.is_file()


def test_migrate_without_sessions_dir_is_noop(tmp_path: Path) -> None:
    p = Paths(config_dir=tmp_path / "c", data_dir=tmp_path / "d", log_dir=tmp_path / "l")
    assert migrate_keystroke_files(p) == 0
