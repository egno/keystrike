"""TOML-backed AdvisorConfigRepository: `advisors.toml` next to
`settings.toml`.

Not part of git sync (`sync_git._SYNC_REL_PATHS`), so each device decides
for itself which advisor runs and whether it may send practice data.

    active = "rules"
    confirmed_off_device = ["llm"]

    [llm]
    provider = "ollama"

Each section is a plain `str -> str` mapping; the advisor's `create`
parses it. An old `ai.toml` (the AI coach) is read once, as the `[llm]`
section, when `advisors.toml` does not exist yet."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import cast

from keystrike.domain.advice import DEFAULT_RECENCY_DECAY, AdvisorConfig

from .atomic_write import atomic_write_text
from .paths import Paths
from .toml_escape import escape_toml_string

DEFAULT_ACTIVE = "rules"
LEGACY_ADVISOR = "llm"


def _read_toml(path: Path) -> dict[str, object] | None:
    if not path.exists():
        return None
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError):
        return None


def _strings(table: object) -> dict[str, str]:
    if not isinstance(table, dict):
        return {}
    return {k: v for k, v in cast("dict[str, object]", table).items() if isinstance(v, str)}


def _decay(raw: object) -> float:
    """A weight ratio in (0, 1]; anything else means the default."""
    if isinstance(raw, int | float) and not isinstance(raw, bool) and 0.0 < raw <= 1.0:
        return float(raw)
    return DEFAULT_RECENCY_DECAY


def _from_table(raw: dict[str, object]) -> AdvisorConfig:
    active = raw.get("active")
    confirmed = raw.get("confirmed_off_device")
    sections = {
        name: _strings(cast("object", value))
        for name, value in raw.items()
        if isinstance(value, dict)
    }
    decay = raw.get("recency_decay")
    return AdvisorConfig(
        recency_decay=_decay(decay),
        active=active if isinstance(active, str) else DEFAULT_ACTIVE,
        confirmed_off_device=tuple(v for v in cast("list[object]", confirmed) if isinstance(v, str))
        if isinstance(confirmed, list)
        else (),
        sections=sections,
    )


class TomlAdvisorConfigRepository:
    def __init__(self, paths: Paths) -> None:
        self._paths = paths

    def load(self) -> AdvisorConfig:
        raw = _read_toml(self._paths.advisors_file)
        if raw is not None:
            return _from_table(raw)
        legacy = self._load_legacy()
        return legacy if legacy is not None else AdvisorConfig(active=DEFAULT_ACTIVE)

    def _load_legacy(self) -> AdvisorConfig | None:
        """The AI coach settings, kept as the `llm` advisor's section. The
        coach was opt-in, so an old config with a provider keeps it on (and
        already confirmed); with none, the new default applies."""
        old = _read_toml(self._paths.ai_settings_file)
        if old is None:
            return None
        section = _strings(old)
        if not section.get("provider"):
            return AdvisorConfig(active=DEFAULT_ACTIVE, sections={LEGACY_ADVISOR: section})
        return AdvisorConfig(
            active=LEGACY_ADVISOR,
            confirmed_off_device=(LEGACY_ADVISOR,),
            sections={LEGACY_ADVISOR: section},
        )

    def save(self, config: AdvisorConfig) -> None:
        confirmed = ", ".join(f'"{escape_toml_string(n)}"' for n in config.confirmed_off_device)
        lines = [
            "# keystrike advisors — local to this device, never synced.\n",
            "# Secrets never go here; an advisor's settings name the environment variable.\n",
            f'active = "{escape_toml_string(config.active)}"\n',
            f"confirmed_off_device = [{confirmed}]\n",
            "# Weight ratio between a session and the next older one (1.0 = all the same).\n",
            f"recency_decay = {config.recency_decay!r}\n",
        ]
        for name, section in config.sections.items():
            lines.append(f"\n[{_bare_or_quoted(name)}]\n")
            lines.extend(
                f'{_bare_or_quoted(key)} = "{escape_toml_string(value)}"\n'
                for key, value in section.items()
            )
        atomic_write_text(self._paths.advisors_file, "".join(lines))


def _bare_or_quoted(key: str) -> str:
    if key and all(c.isalnum() or c in "_-" for c in key):
        return key
    return f'"{escape_toml_string(key)}"'
