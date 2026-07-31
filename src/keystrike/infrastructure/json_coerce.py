"""Validated extraction helpers for untrusted JSON-derived data.

`json.loads` types everything as `Any`/`object`, so pyright strict correctly
refuses an unchecked `int(entry["key"])` on a `dict[str, object]` — `object`
isn't `ConvertibleToInt`/`ConvertibleToFloat`. These helpers isinstance-check
the raw value before casting and raise `KeyError`/`TypeError` on missing or
wrong-typed keys, so callers can catch a narrow set of exceptions to degrade
gracefully on corrupt/malformed data instead of suppressing the type error
with `# type: ignore`.
"""

from __future__ import annotations

from typing import Final

_MISSING: Final[object] = object()


def _lookup(entry: dict[str, object], key: str, default: object) -> object:
    if default is _MISSING:
        if key not in entry:
            raise KeyError(key)
        return entry[key]
    return entry.get(key, default)


def coerce_int(value: object, *, label: str = "value") -> int:
    """Validate that `value` is `int`-convertible (`int` or numeric `str`,
    never `bool`) and return it as `int`.

    `str` is accepted because JSON object keys are always strings (e.g. the
    codepoint keys of a `key_confidence` mapping), so a numeric string here
    reflects normal encoding, not corrupt data.
    """
    if isinstance(value, bool):
        raise TypeError(f"expected int for {label}, got bool: {value!r}")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError as exc:
            raise ValueError(f"expected int for {label}, got non-numeric str: {value!r}") from exc
    raise TypeError(f"expected int for {label}, got {type(value).__name__}: {value!r}")


def coerce_float(value: object, *, label: str = "value") -> float:
    """Validate that `value` is `float`-convertible (`int`, `float`, or
    numeric `str`, never `bool`) and return it as `float`."""
    if isinstance(value, bool):
        raise TypeError(f"expected float for {label}, got bool: {value!r}")
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError as exc:
            raise ValueError(
                f"expected float for {label}, got non-numeric str: {value!r}",
            ) from exc
    raise TypeError(f"expected float for {label}, got {type(value).__name__}: {value!r}")


def coerce_str(value: object, *, label: str = "value") -> str:
    """Validate that `value` is a `str` and return it."""
    if not isinstance(value, str):
        raise TypeError(f"expected str for {label}, got {type(value).__name__}: {value!r}")
    return value


def require_int(entry: dict[str, object], key: str, default: object = _MISSING) -> int:
    """Look up `key` in `entry` (or use `default` if provided) as an `int`.

    Raises `KeyError` if `key` is missing and no `default` was given, or
    `TypeError` if the value isn't an `int`.
    """
    return coerce_int(_lookup(entry, key, default), label=repr(key))


def require_float(entry: dict[str, object], key: str, default: object = _MISSING) -> float:
    """Look up `key` in `entry` (or use `default` if provided) as a `float`.

    Raises `KeyError` if `key` is missing and no `default` was given, or
    `TypeError` if the value isn't numeric.
    """
    return coerce_float(_lookup(entry, key, default), label=repr(key))


def require_str(entry: dict[str, object], key: str, default: object = _MISSING) -> str:
    """Look up `key` in `entry` (or use `default` if provided) as a `str`.

    Raises `KeyError` if `key` is missing and no `default` was given, or
    `TypeError` if the value isn't a `str`.
    """
    return coerce_str(_lookup(entry, key, default), label=repr(key))
