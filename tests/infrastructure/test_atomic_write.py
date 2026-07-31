import os
import sys
from contextlib import suppress
from unittest.mock import patch

import pytest

from keystrike.infrastructure.atomic_write import atomic_write_text


def test_writes_contents_and_replaces_atomically(tmp_path):
    path = tmp_path / "config.toml"
    atomic_write_text(path, "a = 1\n")
    assert path.read_text(encoding="utf-8") == "a = 1\n"

    atomic_write_text(path, "a = 2\n")
    assert path.read_text(encoding="utf-8") == "a = 2\n"


def test_no_leftover_temp_files(tmp_path):
    path = tmp_path / "config.toml"
    atomic_write_text(path, "a = 1\n")
    assert list(tmp_path.iterdir()) == [path]


_SKIP_WIN32 = pytest.mark.skipif(sys.platform == "win32", reason="no Unix mode bits on Windows")


@_SKIP_WIN32
def test_new_file_gets_0644_permissions(tmp_path):
    path = tmp_path / "config.toml"
    atomic_write_text(path, "a = 1\n")
    assert (path.stat().st_mode & 0o777) == 0o644


@_SKIP_WIN32
def test_preserves_existing_file_permissions(tmp_path):
    path = tmp_path / "config.toml"
    atomic_write_text(path, "a = 1\n")
    os.chmod(path, 0o600)

    atomic_write_text(path, "a = 2\n")
    assert (path.stat().st_mode & 0o777) == 0o600


def test_fsync_is_called_before_replace(tmp_path):
    path = tmp_path / "config.toml"
    with patch("keystrike.infrastructure.atomic_write.os.fsync") as mock_fsync:
        atomic_write_text(path, "a = 1\n")
    mock_fsync.assert_called_once()
    assert path.read_text(encoding="utf-8") == "a = 1\n"


def test_temp_file_cleaned_up_on_write_failure(tmp_path):
    path = tmp_path / "config.toml"
    with (
        patch("keystrike.infrastructure.atomic_write.os.fsync", side_effect=OSError("disk full")),
        suppress(OSError),
    ):
        atomic_write_text(path, "a = 1\n")
    assert list(tmp_path.iterdir()) == []
    assert not path.exists()
