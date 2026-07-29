"""TOML-backed SettingsRepository. Reads via stdlib tomllib; writes hand-rolled
TOML for the small Settings dataclass (all scalar fields, no nesting)."""

from __future__ import annotations

import tomllib
from datetime import UTC, datetime

from keystrike.domain.enums import TargetSpeedUnit
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

        defaults = Settings()
        unit_raw = str(raw.get("target_speed_unit", defaults.target_speed_unit))
        try:
            target_speed_unit = TargetSpeedUnit(unit_raw)
        except ValueError:
            target_speed_unit = defaults.target_speed_unit
        return Settings(
            schema_version=int(raw.get("schema_version", defaults.schema_version)),
            layout=str(raw.get("layout", defaults.layout)),
            target_speed_cpm=int(raw.get("target_speed_cpm", defaults.target_speed_cpm)),
            target_speed_unit=target_speed_unit,
            alphabet_size=int(raw.get("alphabet_size", defaults.alphabet_size)),
            confidence_session_window=int(
                raw.get("confidence_session_window", defaults.confidence_session_window),
            ),
            min_confidence_attempts=int(
                raw.get("min_confidence_attempts", defaults.min_confidence_attempts),
            ),
            min_transition_confidence_attempts=int(
                raw.get(
                    "min_transition_confidence_attempts",
                    defaults.min_transition_confidence_attempts,
                ),
            ),
            lang=str(raw.get("lang", defaults.lang)),
            learn_daily_minutes=int(
                raw.get("learn_daily_minutes", defaults.learn_daily_minutes),
            ),
            wordlist_url=str(raw.get("wordlist_url", defaults.wordlist_url)),
            updated_at=(
                str(raw["updated_at"]) if raw.get("updated_at") is not None else None
            ),
        )

    def save(self, settings: Settings) -> None:
        lines = ["# keystrike settings — edit with care, or use the Settings screen.\n"]
        fields: list[tuple[str, object]] = [
            ("schema_version", settings.schema_version),
            ("layout", settings.layout),
            ("target_speed_cpm", settings.target_speed_cpm),
            ("target_speed_unit", settings.target_speed_unit),
            ("alphabet_size", settings.alphabet_size),
            ("confidence_session_window", settings.confidence_session_window),
            ("min_confidence_attempts", settings.min_confidence_attempts),
            (
                "min_transition_confidence_attempts",
                settings.min_transition_confidence_attempts,
            ),
            ("learn_daily_minutes", settings.learn_daily_minutes),
            ("lang", settings.lang),
        ]
        if settings.wordlist_url:
            fields.append(("wordlist_url", settings.wordlist_url))
        for key, value in fields:
            lines.append(f"{key} = {_fmt_scalar(value)}\n")
        lines.append(f"updated_at = {_fmt_scalar(datetime.now(UTC).isoformat())}\n")
        atomic_write_text(self._paths.settings_file, "".join(lines))
