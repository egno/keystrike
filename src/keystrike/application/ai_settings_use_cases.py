"""Use cases for the AI coach settings (`AiSettings`, stored apart from the
synced `Settings`)."""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlparse

from keystrike.application.ai_analyzer import RESPONSE_SCHEMA, ClientFactory, parse_response
from keystrike.domain.ai_models import AI_PROVIDERS, AiSettings
from keystrike.domain.protocols import AiSettingsRepository, KeystrokeArchive


class AiSettingsValidationError(ValueError):
    """Raised by UpdateAiSettings when a proposed change is invalid."""


def _noop() -> None:
    pass


def validate_ai_settings(settings: AiSettings) -> AiSettings:
    provider = settings.provider.strip()
    model = settings.model.strip()
    endpoint = settings.endpoint.strip()
    if provider not in AI_PROVIDERS:
        raise AiSettingsValidationError(f"Unknown AI provider {provider!r}.")
    if provider:
        if not model:
            raise AiSettingsValidationError("AI model is required.")
        parsed = urlparse(endpoint)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise AiSettingsValidationError("AI endpoint must be an http(s) URL.")
    return AiSettings(provider=provider, model=model, endpoint=endpoint)


@dataclass(slots=True)
class UpdateAiSettings:
    """Validate and save the AI coach settings. Turning the coach off also
    deletes the local raw keystroke archive and the kept analyses."""

    repo: AiSettingsRepository
    archive: KeystrokeArchive | None = None
    forget_analyses: Callable[[], None] = _noop

    def __call__(self, proposed: AiSettings) -> AiSettings:
        settings = validate_ai_settings(proposed)
        self.repo.save(settings)
        if not settings.enabled:
            if self.archive is not None:
                # a failure is retried on the next finished session
                with contextlib.suppress(OSError):
                    self.archive.clear()
            self.forget_analyses()
        return settings


_PING_SYSTEM = (
    "Reply with ONLY this JSON object: "
    '{"summary": "ok", "focus_key": null, "focus_pair": null, '
    '"rest_keys": [], "emphasis_keys": []}'
)


@dataclass(slots=True)
class CheckAiConnection:
    """Send one tiny request with `settings` (not yet saved) and report
    whether the server answered with usable JSON."""

    client_factory: ClientFactory

    async def __call__(self, proposed: AiSettings) -> str:
        """A short success message; raises on any failure."""
        settings = validate_ai_settings(proposed)
        if not settings.enabled:
            raise AiSettingsValidationError("Choose an AI provider first.")
        client = self.client_factory(settings)
        reply = await client.chat(_PING_SYSTEM, "ping", schema=RESPONSE_SCHEMA)
        parse_response(reply, frozenset())
        return f"Connected: {settings.model} replied."
