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
