"""Loads free-practice text from a user-chosen .txt file, wrapped to a fixed width."""

from __future__ import annotations

import textwrap
from pathlib import Path


class FileFreeformTextProvider:
    def __init__(self, width: int = 80) -> None:
        self._width = width

    def load(self, path: Path) -> str:
        raw = path.read_text(encoding="utf-8")
        paragraphs = [p.strip() for p in raw.splitlines() if p.strip()]
        wrapped = (textwrap.fill(p, width=self._width) for p in paragraphs)
        return "\n".join(wrapped)
