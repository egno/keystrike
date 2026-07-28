"""Alternate unlock ordering: row-weighted instead of pure frequency.

Mirrors keybr.com's "sort letters in keyboard order" setting
(`Letter.weightedFrequencyOrder`, keyed on `home < top < everything else`,
frequency only breaking ties within a row). Physical row is layout-specific
(`KeyPos.row`), so this genuinely reorders differently per layout — e.g. it
barely touches Colemak/Colemak-DH (their home row already holds most of the
high-frequency letters) but reshuffles QWERTY heavily (only a/s/d/h of the
top-10 frequency letters are home row there).
"""

from __future__ import annotations

from .models import Layout

_HOME_ROW = 1
_TOP_ROW = 0


def _row_weight(layout: Layout, codepoint: int) -> int:
    row = layout.keys[codepoint].row
    if row == _HOME_ROW:
        return 0
    if row == _TOP_ROW:
        return 1
    return 2


def keyboard_order(layout: Layout) -> tuple[int, ...]:
    """`layout.learn_order` with its alphabetic prefix stable-sorted by row
    (home, then top, then everything else) instead of pure frequency. The
    punctuation/space suffix is left untouched — keybr's row-weighting only
    ever applies to letters."""
    letters = [cp for cp in layout.learn_order if chr(cp).isalpha()]
    rest = tuple(cp for cp in layout.learn_order if not chr(cp).isalpha())
    ordered_letters = sorted(letters, key=lambda cp: _row_weight(layout, cp))
    return tuple(ordered_letters) + rest
