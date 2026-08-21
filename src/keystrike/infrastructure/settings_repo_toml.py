"""TOML-backed SettingsRepository. Reads via stdlib tomllib; writes hand-rolled
TOML for the Settings dataclass. Settings is mostly scalar fields, plus a
handful of nested tuning dataclasses (`UnlockTuning`, `FocusTuning`,
`WordGenBounds`) written as their own `[table]` sections."""

from __future__ import annotations

import dataclasses
import tomllib
from datetime import UTC, datetime
from typing import cast

from keystrike.domain.enums import TargetSpeedUnit
from keystrike.domain.models import FocusTuning, Settings, UnlockTuning, WordGenBounds

from .atomic_write import atomic_write_text
from .paths import Paths
from .toml_escape import escape_toml_string

_NestedTuning = UnlockTuning | FocusTuning | WordGenBounds
# Kept as a literal tuple (not derived from `_NestedTuning` via
# `typing.get_args`) so pyright can narrow `isinstance(value, _NESTED_TYPES)`
# -- a runtime-computed tuple loses that. `test_settings_repo_toml.py`'s
# `test_nested_types_matches_nested_tuning_union` guards the two from
# drifting apart instead.
_NESTED_TYPES = (UnlockTuning, FocusTuning, WordGenBounds)


def _fmt_scalar(v: object) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return repr(v)
    if isinstance(v, str):
        return f'"{escape_toml_string(v)}"'
    raise TypeError(f"unsupported settings value type: {type(v).__name__}")


def _coerce_field(default: object, raw_value: object) -> object:
    # Dispatches on the *default value's* runtime type rather than the
    # dataclass field's declared type, so this stays correct regardless of
    # whether Settings uses postponed annotation evaluation.
    if isinstance(default, TargetSpeedUnit):
        return TargetSpeedUnit(str(raw_value))
    if isinstance(default, bool):
        if not isinstance(raw_value, bool):
            raise TypeError(f"expected bool, got {type(raw_value).__name__}")
        return raw_value
    if isinstance(default, int):
        if isinstance(raw_value, bool):
            # bool is an int subclass -- without this, a stray `true`/`false`
            # for an int field (e.g. hand-edited alphabet_size) would
            # silently coerce to 1/0 instead of falling back to the default.
            raise TypeError(f"expected int, got {type(raw_value).__name__}")
        return int(raw_value)  # type: ignore[call-overload]
    if isinstance(default, float):
        return float(raw_value)  # type: ignore[arg-type]
    if isinstance(default, str):
        return str(raw_value)
    raise AssertionError(f"unsupported settings field type: {type(default)!r}")


def _load_nested(cls: type[_NestedTuning], raw_table: object) -> _NestedTuning:
    """Reconstruct a nested tuning dataclass from its TOML sub-table,
    falling back per-field (and wholesale, for a missing/malformed table)
    to `cls()` defaults -- mirrors `load()`'s top-level fallback behavior."""
    defaults = cls()
    if not isinstance(raw_table, dict):
        return defaults
    table = cast("dict[str, object]", raw_table)
    values: dict[str, object] = {}
    for f in dataclasses.fields(defaults):
        default = getattr(defaults, f.name)
        try:
            values[f.name] = _coerce_field(default, table.get(f.name, default))
        except (ValueError, TypeError):
            values[f.name] = default
    return cls(**values)  # type: ignore[arg-type]


def _write_nested_table(lines: list[str], name: str, value: _NestedTuning) -> None:
    lines.append(f"\n[{name}]\n")
    for f in dataclasses.fields(value):
        lines.append(f"{f.name} = {_fmt_scalar(getattr(value, f.name))}\n")


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
            if isinstance(default, _NESTED_TYPES):
                values[f.name] = _load_nested(type(default), raw.get(f.name))
                continue
            try:
                values[f.name] = _coerce_field(default, raw.get(f.name, default))
            except (ValueError, TypeError):
                # A hand-edited or stale settings.toml shouldn't be able to crash
                # startup — fall back to this field's default and keep the rest.
                values[f.name] = default
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
        # Nested tuning tables are buffered separately and appended last --
        # TOML requires every root-level key (including `updated_at` below)
        # to appear before any `[table]` header, regardless of the order
        # Settings declares its fields in.
        table_lines: list[str] = []
        for field in dataclasses.fields(settings):
            if field.name == "updated_at":
                continue  # written fresh below, not round-tripped from the input
            value = getattr(settings, field.name)
            if isinstance(value, _NESTED_TYPES):
                _write_nested_table(table_lines, field.name, value)
                continue
            if field.name == "wordlist_url" and not value:
                continue  # omit when unset, matching prior hand-rolled behavior
            lines.append(f"{field.name} = {_fmt_scalar(value)}\n")
        lines.append(f"updated_at = {_fmt_scalar(datetime.now(UTC).isoformat())}\n")
        lines.extend(table_lines)
        atomic_write_text(self._paths.settings_file, "".join(lines))
