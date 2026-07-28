"""Snippet selection for the code-practice mode.

Unlike English word generation (M3's Markov model), real code has mandatory
syntax characters that can't be filtered out to just the unlocked alphabet —
a hard character-set filter would reject almost every real snippet early on.
Instead, prefer snippets that exercise the current focus key more.
"""

from __future__ import annotations

from collections.abc import Sequence
from random import Random


def select_snippet(snippets: Sequence[str], focus_char: str, rng: Random) -> str:
    if not snippets:
        raise ValueError("no snippets available")
    weights = [snippet.count(focus_char) + 1 for snippet in snippets]
    return rng.choices(snippets, weights=weights, k=1)[0]
