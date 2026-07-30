"""POSIX + Windows atomic file replace: write to temp, then os.replace."""

from __future__ import annotations

import os
from pathlib import Path


def atomic_write_text(path: Path, contents: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_text(contents, encoding="utf-8")
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    os.replace(tmp, path)
