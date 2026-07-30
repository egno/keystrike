from pathlib import Path

import pytest

from keystrike.infrastructure.layout_repo import CompositeLayoutRepository
from keystrike.infrastructure.layout_toml import LayoutTomlError
from keystrike.infrastructure.paths import Paths


@pytest.fixture
def paths(tmp_path: Path) -> Paths:
    return Paths(
        config_dir=tmp_path / "config",
        data_dir=tmp_path / "data",
        log_dir=tmp_path / "log",
    )


def test_lists_bundled_layouts_without_config_dir(paths: Paths):
    repo = CompositeLayoutRepository(paths)
    assert {"qwerty", "dvorak", "colemak", "colemak_dh"}.issubset(set(repo.list_available()))


def test_get_bundled_layout(paths: Paths):
    repo = CompositeLayoutRepository(paths)
    assert repo.get("qwerty").name == "qwerty"


def test_get_unknown_layout_raises(paths: Paths):
    repo = CompositeLayoutRepository(paths)
    with pytest.raises(KeyError):
        repo.get("nope")


def test_discovers_custom_toml_layout(paths: Paths):
    paths.layouts_dir.mkdir(parents=True)
    (paths.layouts_dir / "myown.toml").write_text(
        'name = "myown"\nlearn_order = "a"\n\n'
        '[[keys]]\nchar = "a"\nrow = 1\ncol = 0\nfinger = "PINKY"\nhand = "L"\n',
        encoding="utf-8",
    )
    repo = CompositeLayoutRepository(paths)
    assert "myown" in repo.list_available()
    layout = repo.get("myown")
    assert layout.name == "myown"
    assert layout.keys[ord("a")].col == 0


def test_bundled_takes_priority_over_same_named_toml(paths: Paths):
    paths.layouts_dir.mkdir(parents=True)
    (paths.layouts_dir / "qwerty.toml").write_text(
        'name = "should-not-be-used"\nlearn_order = "a"\n\n'
        '[[keys]]\nchar = "a"\nrow = 0\ncol = 0\nfinger = "PINKY"\nhand = "L"\n',
        encoding="utf-8",
    )
    repo = CompositeLayoutRepository(paths)
    assert repo.get("qwerty").name == "qwerty"


def test_get_raises_on_invalid_toml_listed_by_list_available(paths: Paths):
    paths.layouts_dir.mkdir(parents=True)
    (paths.layouts_dir / "broken.toml").write_text("not valid toml [[", encoding="utf-8")
    repo = CompositeLayoutRepository(paths)
    assert "broken" in repo.list_available()
    with pytest.raises(LayoutTomlError):
        repo.get("broken")


def test_uses_filename_stem_as_id_not_name_field(paths: Paths):
    paths.layouts_dir.mkdir(parents=True)
    (paths.layouts_dir / "file_stem.toml").write_text(
        'name = "display_name"\nlearn_order = "a"\n\n'
        '[[keys]]\nchar = "a"\nrow = 1\ncol = 0\nfinger = "PINKY"\nhand = "L"\n',
        encoding="utf-8",
    )
    repo = CompositeLayoutRepository(paths)
    assert "file_stem" in repo.list_available()
    assert "display_name" not in repo.list_available()
    layout = repo.get("file_stem")
    assert layout.name == "display_name"
