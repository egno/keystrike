from keystrike.domain.learn_order import keyboard_order
from keystrike.infrastructure.bundled_layouts.colemak_dh import LAYOUT as COLEMAK_DH
from keystrike.infrastructure.bundled_layouts.qwerty import LAYOUT as QWERTY


def test_qwerty_keyboard_order_groups_by_row_home_then_top_then_bottom():
    order = keyboard_order(QWERTY)
    letters = [cp for cp in order if chr(cp).isalpha()]
    rows = [QWERTY.keys[cp].row for cp in letters]
    assert rows == sorted(rows, key=lambda r: {1: 0, 0: 1}.get(r, 2))


def test_qwerty_keyboard_order_matches_expected_sequence():
    # Home row a s d f g h j k l, sorted by ETAOIN-SHRDLU frequency rank:
    # a(2) s(6) h(7) d(9) l(10) f(15) g(16) k(21) j(22).
    order = keyboard_order(QWERTY)
    home_tier = "".join(chr(cp) for cp in order if chr(cp).isalpha() and QWERTY.keys[cp].row == 1)
    assert home_tier == "ashdlfgkj"


def test_qwerty_keyboard_order_differs_from_frequency_order():
    assert keyboard_order(QWERTY) != QWERTY.learn_order


def test_keyboard_order_preserves_punctuation_and_space_suffix():
    order = keyboard_order(QWERTY)
    non_alpha_original = tuple(cp for cp in QWERTY.learn_order if not chr(cp).isalpha())
    non_alpha_reordered = tuple(cp for cp in order if not chr(cp).isalpha())
    assert non_alpha_reordered == non_alpha_original


def test_colemak_dh_keyboard_order_diverges_from_plain_frequency_at_h_and_d():
    # h/d were moved off the Colemak-DH home row to the bottom row (see
    # colemak_dh.py), so even this "optimized" layout's keyboard order isn't
    # identical to its plain frequency order past the first 7 letters.
    order = keyboard_order(COLEMAK_DH)
    first_ten = "".join(chr(cp) for cp in order[:10])
    assert first_ten == "etaoinsrmg"
    assert first_ten != "".join(chr(cp) for cp in COLEMAK_DH.learn_order[:10])
