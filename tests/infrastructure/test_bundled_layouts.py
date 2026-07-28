import pytest

from keystrike.infrastructure.bundled_layouts.colemak import LAYOUT as COLEMAK
from keystrike.infrastructure.bundled_layouts.colemak_dh import LAYOUT as COLEMAK_DH
from keystrike.infrastructure.bundled_layouts.dvorak import LAYOUT as DVORAK
from keystrike.infrastructure.bundled_layouts.qwerty import LAYOUT as QWERTY

_ALL = (QWERTY, DVORAK, COLEMAK, COLEMAK_DH)


def _id(layout):
    return layout.name


@pytest.mark.parametrize("layout", _ALL, ids=_id)
def test_contains_all_lowercase_letters(layout):
    letters = {cp for cp in layout.keys if chr(cp).isalpha()}
    assert letters == {ord(c) for c in "abcdefghijklmnopqrstuvwxyz"}


@pytest.mark.parametrize("layout", _ALL, ids=_id)
def test_contains_space(layout):
    assert ord(" ") in layout.keys


@pytest.mark.parametrize("layout", _ALL, ids=_id)
def test_learn_order_covers_every_key_exactly_once(layout):
    assert sorted(layout.learn_order) == sorted(layout.keys)
    assert len(layout.learn_order) == len(set(layout.learn_order))


def test_layouts_have_distinct_names():
    assert {layout.name for layout in _ALL} == {"qwerty", "dvorak", "colemak", "colemak_dh"}


def test_qwerty_home_row_starts_at_a():
    a_pos = QWERTY.keys[ord("a")]
    assert a_pos.row == 1
    assert a_pos.col == 0


def test_colemak_dh_moves_d_and_h_off_home_row():
    # The defining change vs. standard Colemak: D and H curl down to the
    # bottom row's inner (index-finger) columns instead of sitting on the
    # home row's inner columns.
    d_pos = COLEMAK_DH.keys[ord("d")]
    h_pos = COLEMAK_DH.keys[ord("h")]
    assert d_pos.row == 2
    assert h_pos.row == 2
    assert d_pos.col == 3
    assert h_pos.col == 6


def test_colemak_dh_g_reclaims_qwerty_home_row_position():
    g_pos = COLEMAK_DH.keys[ord("g")]
    assert g_pos.row == 1
    assert g_pos.col == 4


def test_colemak_dh_is_ortholinear():
    assert COLEMAK_DH.ortholinear is True


@pytest.mark.parametrize("layout", [QWERTY, DVORAK, COLEMAK], ids=_id)
def test_traditional_layouts_are_staggered(layout):
    assert layout.ortholinear is False
