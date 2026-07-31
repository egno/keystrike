"""Shared TOML basic-string escaping for hand-written TOML writers."""

from __future__ import annotations


def escape_toml_string(value: str) -> str:
    """Escape `value` for embedding in a TOML basic string (`"..."`)."""
    return value.replace("\\", "\\\\").replace('"', '\\"')
