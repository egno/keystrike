"""Shared builder for the three bundled Latin keyboard layouts.

Each layout is three 10-key rows (top / home / bottom) laid out on the
physical QWERTY grid; only which *character* sits at each physical position
changes between QWERTY, Dvorak, and Colemak. Finger/hand assignment is
therefore identical across all three — it depends on the physical column,
not the character.
"""

from __future__ import annotations

from keystrike.domain.enums import Finger, Hand
from keystrike.domain.models import KeyPos, Layout

_FINGER_HAND_BY_COL: tuple[tuple[Finger, Hand], ...] = (
    (Finger.PINKY, Hand.L),
    (Finger.RING, Hand.L),
    (Finger.MIDDLE, Hand.L),
    (Finger.INDEX, Hand.L),
    (Finger.INDEX, Hand.L),
    (Finger.INDEX, Hand.R),
    (Finger.INDEX, Hand.R),
    (Finger.MIDDLE, Hand.R),
    (Finger.RING, Hand.R),
    (Finger.PINKY, Hand.R),
)

# Classic "ETAOIN SHRDLU" English letter-frequency ordering, used to unlock
# keys roughly easiest/most-common first regardless of physical layout.
_LETTER_FREQUENCY = "etaoinshrdlcumwfgypbvkjxqz"

_SPACE_ROW = 3
_SPACE_COL = 4
_ROW_WIDTH = 10


def build_layout(name: str, rows: tuple[str, str, str], *, ortholinear: bool = False) -> Layout:
    keys: dict[int, KeyPos] = {}
    punctuation: list[str] = []

    for row_index, row in enumerate(rows):
        if len(row) != _ROW_WIDTH:
            raise ValueError(f"{name}: row {row_index} must have exactly 10 keys, got {row!r}")
        for col, ch in enumerate(row):
            finger, hand = _FINGER_HAND_BY_COL[col]
            keys[ord(ch)] = KeyPos(
                codepoint=ord(ch), row=row_index, col=col, finger=finger, hand=hand,
            )
            if not ch.isalpha():
                punctuation.append(ch)

    keys[ord(" ")] = KeyPos(
        codepoint=ord(" "), row=_SPACE_ROW, col=_SPACE_COL, finger=Finger.THUMB, hand=Hand.L,
    )

    learn_order = (
        tuple(ord(c) for c in _LETTER_FREQUENCY if ord(c) in keys)
        + tuple(ord(c) for c in punctuation)
        + (ord(" "),)
    )
    return Layout(name=name, keys=keys, learn_order=learn_order, ortholinear=ortholinear)
