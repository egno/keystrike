from __future__ import annotations

from dataclasses import dataclass

from .models import Bigram


@dataclass(frozen=True, slots=True)
class AiAnalysis:
    """Coaching suggestions for the next lesson. Codepoints only — the
    analyzer maps whatever the model says onto validated codepoints.

    `error` is non-empty when the analysis could not be produced (provider
    down, unparseable reply); every suggestion field is then empty."""

    summary: str = ""
    focus_key: int | None = None
    focus_pair: Bigram | None = None
    rest_keys: tuple[int, ...] = ()
    emphasis_keys: tuple[int, ...] = ()
    error: str = ""

    @property
    def failed(self) -> bool:
        return bool(self.error)
