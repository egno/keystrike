"""TOML -> Layout parser for user-defined custom layouts.

Expected file shape (`<config>/keystrike/layouts/<name>.toml`):

    name = "my_layout"
    learn_order = "etaoinshrdlcumwfgypbvkjxqz;,./ "
    ortholinear = false  # optional, default false; true renders Stats without row-stagger

    [[keys]]
    char = "a"
    row = 1
    col = 0
    finger = "PINKY"
    hand = "L"
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import cast

from keystrike.domain.enums import Finger, Hand
from keystrike.domain.models import KeyPos, Layout


class LayoutTomlError(ValueError):
    pass


def load_layout_toml(file: Path) -> Layout:
    try:
        raw = tomllib.loads(file.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise LayoutTomlError(f"{file}: {exc}") from exc

    name = raw.get("name")
    if not isinstance(name, str) or not name:
        raise LayoutTomlError(f"{file}: missing required string field 'name'")

    raw_keys = raw.get("keys")
    if not isinstance(raw_keys, list) or not raw_keys:
        raise LayoutTomlError(f"{file}: missing required non-empty array of tables 'keys'")

    keys: dict[int, KeyPos] = {}
    for index, entry in enumerate(cast("list[object]", raw_keys)):
        if not isinstance(entry, dict):
            raise LayoutTomlError(f"{file}: keys[{index}] must be a table")
        pos = _parse_key(file, index, cast("dict[str, object]", entry))
        keys[pos.codepoint] = pos

    raw_learn_order = raw.get("learn_order")
    if not isinstance(raw_learn_order, str) or not raw_learn_order:
        raise LayoutTomlError(f"{file}: missing required string field 'learn_order'")
    unknown = [c for c in raw_learn_order if ord(c) not in keys]
    if unknown:
        raise LayoutTomlError(f"{file}: learn_order references undefined keys: {unknown!r}")

    learn_order = tuple(ord(c) for c in raw_learn_order)

    ortholinear = raw.get("ortholinear", False)
    if not isinstance(ortholinear, bool):
        raise LayoutTomlError(f"{file}: 'ortholinear' must be a boolean")

    return Layout(name=name, keys=keys, learn_order=learn_order, ortholinear=ortholinear)


def _parse_key(file: Path, index: int, entry: dict[str, object]) -> KeyPos:
    char = entry.get("char")
    if not isinstance(char, str) or len(char) != 1:
        raise LayoutTomlError(f"{file}: keys[{index}].char must be a single character")

    row, col = entry.get("row"), entry.get("col")
    if not isinstance(row, int) or not isinstance(col, int):
        raise LayoutTomlError(f"{file}: keys[{index}] requires integer 'row' and 'col'")

    finger_raw = entry.get("finger")
    if not isinstance(finger_raw, str) or finger_raw not in Finger.__members__:
        raise LayoutTomlError(
            f"{file}: keys[{index}].finger must be one of {list(Finger.__members__)}"
        )

    hand_raw = entry.get("hand")
    if not isinstance(hand_raw, str) or hand_raw not in Hand.__members__:
        raise LayoutTomlError(f"{file}: keys[{index}].hand must be one of {list(Hand.__members__)}")

    shifted = entry.get("shifted", False)
    if not isinstance(shifted, bool):
        raise LayoutTomlError(f"{file}: keys[{index}].shifted must be a boolean")

    return KeyPos(
        codepoint=ord(char),
        row=row,
        col=col,
        finger=Finger[finger_raw],
        hand=Hand[hand_raw],
        shifted=shifted,
    )
