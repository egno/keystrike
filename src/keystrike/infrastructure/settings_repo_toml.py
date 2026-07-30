"""TOML-backed SettingsRepository. Reads via stdlib tomllib; writes hand-rolled
TOML for the small Settings dataclass (all scalar fields, no nesting)."""

from __future__ import annotations

import dataclasses
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
        try:
            raw = tomllib.loads(self._paths.settings_file.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError:
            return Settings()

        # Field list (and per-field cast) is derived from the Settings dataclass
        # itself, mirroring save(), so load/save can't silently drift apart when
        # a field is added/removed from Settings.
        defaults = Settings()
        values: dict[str, object] = {}
        for f in dataclasses.fields(Settings):
            if f.name == "updated_at":
                # Written fresh on save(), not defaulted — only round-tripped here.
                raw_updated = raw.get("updated_at")
                values[f.name] = str(raw_updated) if raw_updated is not None else None
                continue
            default = getattr(defaults, f.name)
            if f.type is TargetSpeedUnit:
                try:
                    values[f.name] = TargetSpeedUnit(str(raw.get(f.name, default)))
                except ValueError:
                    values[f.name] = default
            elif f.type is bool:
                values[f.name] = bool(raw.get(f.name, default))
            elif f.type is int:
                values[f.name] = int(raw.get(f.name, default))
            elif f.type is float:
                values[f.name] = float(raw.get(f.name, default))
            elif f.type is str:
                values[f.name] = str(raw.get(f.name, default))
            else:
                raise TypeError(f"unsupported settings field type: {f.type!r}")
        # `values` is built dynamically off `dataclasses.fields(Settings)`, so
        # pyright can't statically match each entry to its declared parameter
        # type the way it could with a hand-written call — the per-field
        # isinstance/cast dispatch above is what actually keeps this sound.
        return Settings(**values)  # type: ignore[arg-type]

    def save(self, settings: Settings) -> None:
        # Field list is derived from the Settings dataclass itself (single
        # source of truth) rather than hand-maintained here, so it can't
        # silently drift when a field is added/removed from Settings.
        lines = ["# keystrike settings — edit with care, or use the Settings screen.\n"]
        for field in dataclasses.fields(settings):
            if field.name == "updated_at":
                continue  # written fresh below, not round-tripped from the input
            value = getattr(settings, field.name)
            if field.name == "wordlist_url" and not value:
                continue  # omit when unset, matching prior hand-rolled behavior
            lines.append(f"{field.name} = {_fmt_scalar(value)}\n")
        lines.append(f"updated_at = {_fmt_scalar(datetime.now(UTC).isoformat())}\n")
        atomic_write_text(self._paths.settings_file, "".join(lines))
