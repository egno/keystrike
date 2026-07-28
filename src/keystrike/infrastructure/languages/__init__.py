"""BundledLanguageProvider: loads pre-built Markov transition tables shipped
with the package (`data/<lang>_markov.json.gz`, produced by scripts/build_markov.py)."""

from __future__ import annotations

import gzip
import json
from importlib import resources
from typing import cast

from keystrike.domain.markov import TransitionTable

_PACKAGE = "keystrike.infrastructure.languages"


class BundledLanguageProvider:
    def __init__(self) -> None:
        self._cache: dict[str, TransitionTable] = {}

    def transitions(self, lang: str) -> TransitionTable:
        cached = self._cache.get(lang)
        if cached is not None:
            return cached

        raw = resources.files(_PACKAGE).joinpath("data", f"{lang}_markov.json.gz").read_bytes()
        payload = cast("dict[str, object]", json.loads(gzip.decompress(raw)))
        table = TransitionTable(
            order=cast("int", payload["order"]),
            transitions=cast("dict[str, dict[str, int]]", payload["transitions"]),
        )
        self._cache[lang] = table
        return table
