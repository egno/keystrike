"""Shared TOML basic-string escaping for hand-written TOML writers."""

from __future__ import annotations

# TOML basic strings forbid raw control characters -- an unescaped newline
# (or other C0 control char) breaks the line structure of the file, and a
# hand-rolled writer has no parser downstream to catch that before it's on
# disk. Named escapes per the TOML spec; anything else in that range falls
# back to \uXXXX.
_ASCII_CONTROL_MAX = 0x1F
_ASCII_DEL = 0x7F

_NAMED_ESCAPES = {
    "\\": "\\\\",
    '"': '\\"',
    "\b": "\\b",
    "\t": "\\t",
    "\n": "\\n",
    "\f": "\\f",
    "\r": "\\r",
}


def escape_toml_string(value: str) -> str:
    """Escape `value` for embedding in a TOML basic string (`"..."`)."""
    out: list[str] = []
    for ch in value:
        if ch in _NAMED_ESCAPES:
            out.append(_NAMED_ESCAPES[ch])
        elif ord(ch) <= _ASCII_CONTROL_MAX or ord(ch) == _ASCII_DEL:
            out.append(f"\\u{ord(ch):04x}")
        else:
            out.append(ch)
    return "".join(out)
