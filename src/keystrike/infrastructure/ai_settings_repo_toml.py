"""TOML-backed AiSettingsRepository: `ai.toml` next to `settings.toml`.

Not part of git sync (`sync_git._SYNC_REL_PATHS`), so each device decides
for itself whether, and where, it sends practice data."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import cast

from keystrike.domain.ai_models import AI_PROVIDERS, AiSettings

from .atomic_write import atomic_write_text
from .paths import Paths
from .toml_escape import escape_toml_string

# Unreleased builds kept these keys in the synced settings.toml.
_LEGACY_KEYS = {"provider": "ai_provider", "model": "ai_model", "endpoint": "ai_endpoint"}


def _read_toml(path: Path) -> dict[str, object] | None:
    if not path.exists():
        return None
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError):
        return None


def _from_table(table: dict[str, object], names: dict[str, str]) -> AiSettings:
    defaults = AiSettings()
    values: dict[str, str] = {}
    for field, key in names.items():
        raw = table.get(key)
        values[field] = raw if isinstance(raw, str) else cast("str", getattr(defaults, field))
    if values["provider"] not in AI_PROVIDERS:
        values["provider"] = defaults.provider
    return AiSettings(**values)


class TomlAiSettingsRepository:
    def __init__(self, paths: Paths) -> None:
        self._paths = paths

    def load(self) -> AiSettings:
        raw = _read_toml(self._paths.ai_settings_file)
        if raw is not None:
            return _from_table(raw, {name: name for name in _LEGACY_KEYS})
        legacy = _read_toml(self._paths.settings_file)
        if legacy is not None and any(key in legacy for key in _LEGACY_KEYS.values()):
            return _from_table(legacy, _LEGACY_KEYS)
        return AiSettings()

    def save(self, settings: AiSettings) -> None:
        lines = [
            "# keystrike AI coach — local to this device, never synced.\n",
            "# API key (OpenAI-compatible servers): set KEYSTRIKE_AI_API_KEY.\n",
            f'provider = "{escape_toml_string(settings.provider)}"\n',
            f'model = "{escape_toml_string(settings.model)}"\n',
            f'endpoint = "{escape_toml_string(settings.endpoint)}"\n',
        ]
        atomic_write_text(self._paths.ai_settings_file, "".join(lines))
