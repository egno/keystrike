"""TOML-backed SettingsRepository. Reads via stdlib tomllib; writes hand-rolled
TOML for the small Settings dataclass (all scalar fields, no nesting)."""

from __future__ import annotations

import tomllib

from keystrike.domain.models import Settings

from .atomic_write import atomic_write_text
from .paths import Paths


def _fmt_scalar(v: object) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return repr(v)
    if isinstance(v, str):
        # TOML basic string: escape backslash and double-quote.
        escaped = v.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    raise TypeError(f"unsupported settings value type: {type(v).__name__}")


class TomlSettingsRepository:
    def __init__(self, paths: Paths) -> None:
        self._paths = paths

    def load(self) -> Settings:
        if not self._paths.settings_file.exists():
            return Settings()
        raw = tomllib.loads(self._paths.settings_file.read_text(encoding="utf-8"))

        # Map raw TOML → Settings. Unknown keys are ignored (forward-compat).
        defaults = Settings()
        return Settings(
            schema_version=int(raw.get("schema_version", defaults.schema_version)),
            layout=str(raw.get("layout", defaults.layout)),
            target_speed_cpm=int(raw.get("target_speed_cpm", defaults.target_speed_cpm)),
            alphabet_size=int(raw.get("alphabet_size", defaults.alphabet_size)),
            lang=str(raw.get("lang", defaults.lang)),
            learn_daily_minutes=int(
                raw.get("learn_daily_minutes", defaults.learn_daily_minutes),
            ),
        )

    def save(self, settings: Settings) -> None:
        lines = ["# keystrike settings — edit with care, or use the Settings screen.\n"]
        fields: list[tuple[str, object]] = [
            ("schema_version", settings.schema_version),
            ("layout", settings.layout),
            ("target_speed_cpm", settings.target_speed_cpm),
            ("alphabet_size", settings.alphabet_size),
            ("learn_daily_minutes", settings.learn_daily_minutes),
            ("lang", settings.lang),
        ]
        for key, value in fields:
            lines.append(f"{key} = {_fmt_scalar(value)}\n")
        atomic_write_text(self._paths.settings_file, "".join(lines))
