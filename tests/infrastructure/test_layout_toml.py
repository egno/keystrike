from pathlib import Path

import pytest

from keystrike.domain.enums import Finger, Hand
from keystrike.infrastructure.layout_toml import LayoutTomlError, load_layout_toml

_FIXTURES = Path(__file__).parent / "fixtures" / "layouts"


def test_loads_good_fixture():
    layout = load_layout_toml(_FIXTURES / "good.toml")
    assert layout.name == "custom_test"
    assert layout.learn_order == (ord("a"), ord("b"))
    a = layout.keys[ord("a")]
    assert a.row == 1
    assert a.col == 0
    assert a.finger is Finger.PINKY
    assert a.hand is Hand.L
    assert layout.keys[ord("b")].finger is Finger.RING
    assert layout.ortholinear is False


def test_loads_ortholinear_fixture():
    layout = load_layout_toml(_FIXTURES / "good_ortholinear.toml")
    assert layout.ortholinear is True


@pytest.mark.parametrize(
    "fixture",
    [
        "bad_syntax.toml",
        "bad_missing_field.toml",
        "bad_finger.toml",
        "bad_unknown_learn_order.toml",
        "bad_ortholinear_type.toml",
    ],
)
def test_rejects_bad_fixtures(fixture: str):
    with pytest.raises(LayoutTomlError):
        load_layout_toml(_FIXTURES / fixture)


def test_missing_name_field(tmp_path: Path):
    file = tmp_path / "no_name.toml"
    file.write_text('learn_order = "a"\n\n[[keys]]\nchar = "a"\nrow = 1\ncol = 0\n'
                     'finger = "PINKY"\nhand = "L"\n', encoding="utf-8")
    with pytest.raises(LayoutTomlError, match="name"):
        load_layout_toml(file)


def test_missing_keys_field(tmp_path: Path):
    file = tmp_path / "no_keys.toml"
    file.write_text('name = "x"\nlearn_order = "a"\n', encoding="utf-8")
    with pytest.raises(LayoutTomlError, match="keys"):
        load_layout_toml(file)


def _write_layout(tmp_path: Path, content: str) -> Path:
    file = tmp_path / "layout.toml"
    file.write_text(content, encoding="utf-8")
    return file


_MINIMAL = (
    'name = "x"\n'
    'learn_order = "a"\n\n'
    '[[keys]]\n'
    'char = "a"\n'
    'row = 1\n'
    'col = 0\n'
    'finger = "PINKY"\n'
    'hand = "L"\n'
)


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("hand", '"X"', "hand"),
        ("char", '"ab"', "char"),
        ("row", '"1"', "row"),
        ("shifted", '"yes"', "shifted"),
    ],
)
def test_rejects_invalid_key_fields(
    tmp_path: Path, field: str, value: str, match: str,
):
    content = _MINIMAL
    if field == "shifted":
        content = content + f"shifted = {value}\n"
    else:
        lines = _MINIMAL.splitlines()
        content = "\n".join(
            f"{field} = {value}" if line.startswith(f"{field} = ") else line
            for line in lines
        ) + "\n"
    with pytest.raises(LayoutTomlError, match=match):
        load_layout_toml(_write_layout(tmp_path, content))


def test_rejects_non_table_keys_entry(tmp_path: Path):
    content = 'name = "x"\nlearn_order = "a"\nkeys = [1]\n'
    with pytest.raises(LayoutTomlError, match=r"keys\[0\] must be a table"):
        load_layout_toml(_write_layout(tmp_path, content))


def test_rejects_empty_learn_order(tmp_path: Path):
    content = _MINIMAL.replace('learn_order = "a"\n', 'learn_order = ""\n')
    with pytest.raises(LayoutTomlError, match="learn_order"):
        load_layout_toml(_write_layout(tmp_path, content))


def test_duplicate_keys_last_entry_wins(tmp_path: Path):
    content = (
        'name = "x"\n'
        'learn_order = "a"\n\n'
        '[[keys]]\n'
        'char = "a"\n'
        'row = 1\n'
        'col = 0\n'
        'finger = "PINKY"\n'
        'hand = "L"\n\n'
        '[[keys]]\n'
        'char = "a"\n'
        'row = 9\n'
        'col = 9\n'
        'finger = "THUMB"\n'
        'hand = "R"\n'
    )
    layout = load_layout_toml(_write_layout(tmp_path, content))
    assert layout.keys[ord("a")].row == 9
    assert layout.keys[ord("a")].finger is Finger.THUMB


def test_loads_shifted_true(tmp_path: Path):
    content = _MINIMAL.replace('hand = "L"\n', 'hand = "L"\nshifted = true\n')
    layout = load_layout_toml(_write_layout(tmp_path, content))
    assert layout.keys[ord("a")].shifted is True
