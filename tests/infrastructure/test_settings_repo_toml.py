import pytest

from keystrike.domain.models import Settings
from keystrike.infrastructure.paths import Paths
from keystrike.infrastructure.settings_repo_toml import TomlSettingsRepository


@pytest.fixture
def paths(tmp_path):
    p = Paths(
        config_dir=tmp_path / "config",
        data_dir=tmp_path / "data",
        log_dir=tmp_path / "logs",
    )
    p.config_dir.mkdir(parents=True, exist_ok=True)
    return p


def test_load_defaults_when_no_file(paths):
    s = TomlSettingsRepository(paths).load()
    assert s == Settings()


def test_round_trip(paths):
    repo = TomlSettingsRepository(paths)
    original = Settings(
        layout="dvorak",
        target_speed_cpm=400,
        alphabet_size=0.75,
        recover_keys=False,
        keyboard_order=True,
        theme="light",
        freeform_path="/tmp/lorem.txt",
    )
    repo.save(original)
    assert repo.load() == original


def test_save_uses_atomic_replace(paths):
    repo = TomlSettingsRepository(paths)
    repo.save(Settings(layout="colemak"))
    text = paths.settings_file.read_text()
    assert 'layout = "colemak"' in text
    assert "schema_version = 1" in text


def test_ignores_unknown_keys_for_forward_compat(paths):
    paths.settings_file.write_text(
        'schema_version = 1\n'
        'layout = "qwerty"\n'
        'unknown_future_key = 42\n',
        encoding="utf-8",
    )
    s = TomlSettingsRepository(paths).load()
    assert s.layout == "qwerty"


def test_quote_and_backslash_escaping(paths):
    repo = TomlSettingsRepository(paths)
    tricky = Settings(freeform_path='C:\\path\\with "quotes" in name.txt')
    repo.save(tricky)
    assert repo.load().freeform_path == tricky.freeform_path
