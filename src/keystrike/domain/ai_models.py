from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from .models import Bigram

AI_PROVIDER_OFF: Final = ""
AI_PROVIDER_OLLAMA: Final = "ollama"
# Any server with an OpenAI-style `/chat/completions` route: llama.cpp,
# LM Studio, vLLM, Ollama's `/v1`, or a hosted API.
AI_PROVIDER_OPENAI: Final = "openai"
AI_PROVIDERS: Final = (AI_PROVIDER_OFF, AI_PROVIDER_OLLAMA, AI_PROVIDER_OPENAI)

DEFAULT_AI_ENDPOINTS: Final = {
    AI_PROVIDER_OLLAMA: "http://localhost:11434",
    AI_PROVIDER_OPENAI: "http://localhost:8080/v1",
}
DEFAULT_AI_MODEL: Final = "llama3.2"


@dataclass(frozen=True, slots=True)
class AiSettings:
    """AI coach configuration. Kept apart from `Settings` on purpose:
    `settings.toml` is git-synced, and turning on a remote endpoint on one
    device must not start sending data from every other device.

    The API key (OpenAI-compatible providers only) is never stored here; it
    is read from the environment by the client."""

    provider: str = AI_PROVIDER_OFF
    model: str = DEFAULT_AI_MODEL
    endpoint: str = DEFAULT_AI_ENDPOINTS[AI_PROVIDER_OLLAMA]

    @property
    def enabled(self) -> bool:
        return bool(self.provider)


@dataclass(frozen=True, slots=True)
class AiAnalysis:
    """Coaching suggestions for the next lesson of one layout. Codepoints
    only — the analyzer maps whatever the model says onto validated
    codepoints.

    `error` is non-empty when the analysis could not be produced (provider
    down, unparseable reply); every suggestion field is then empty."""

    layout: str = ""
    summary: str = ""
    focus_key: int | None = None
    focus_pair: Bigram | None = None
    rest_keys: tuple[int, ...] = ()
    emphasis_keys: tuple[int, ...] = ()
    error: str = ""
    created_at: float = 0.0  # unix epoch; 0 = unknown

    @property
    def failed(self) -> bool:
        return bool(self.error)

    @property
    def actionable(self) -> bool:
        """True when the analysis can steer a lesson at all."""
        return not self.failed and bool(
            self.focus_key is not None
            or self.focus_pair is not None
            or self.rest_keys
            or self.emphasis_keys
        )
