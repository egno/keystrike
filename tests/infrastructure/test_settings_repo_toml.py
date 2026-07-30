import pytest

from keystrike.domain.enums import TargetSpeedUnit
from keystrike.domain.models import Settings
from keystrike.infrastructure.paths import Paths
from keystrike.infrastructure.settings_repo_toml import TomlSettingsRepository, _coerce_field


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
        target_speed_unit=TargetSpeedUnit.WPM,
        alphabet_size=20,
        confidence_session_window=8,
        min_confidence_attempts=12,
        min_transition_confidence_attempts=5,
        focus_char_boost=2.5,
        focus_word_boost=5.0,
        focus_bigram_word_boost=6.0,
        focus_transition_boost=3.5,
        focus_weak_extra_boost=2.0,
    )
    repo.save(original)
    loaded = repo.load()
    assert loaded.layout == original.layout
    assert loaded.target_speed_cpm == original.target_speed_cpm
    assert loaded.confidence_session_window == 8
    assert loaded.min_confidence_attempts == 12
    assert loaded.min_transition_confidence_attempts == 5
    assert loaded.focus_char_boost == 2.5
    assert loaded.focus_word_boost == 5.0
    assert loaded.focus_bigram_word_boost == 6.0
    assert loaded.focus_transition_boost == 3.5
    assert loaded.focus_weak_extra_boost == 2.0
    assert loaded.updated_at is not None


def test_save_uses_atomic_replace(paths):
    repo = TomlSettingsRepository(paths)
    repo.save(Settings(layout="colemak"))
    text = paths.settings_file.read_text()
    assert 'layout = "colemak"' in text
    assert "schema_version = 1" in text


def test_ignores_unknown_keys_for_forward_compat(paths):
    paths.settings_file.write_text(
        'schema_version = 1\nlayout = "qwerty"\nunknown_future_key = 42\n',
        encoding="utf-8",
    )
    s = TomlSettingsRepository(paths).load()
    assert s.layout == "qwerty"


def test_ignores_removed_settings_keys(paths):
    paths.settings_file.write_text(
        "schema_version = 1\n"
        'layout = "qwerty"\n'
        'freeform_path = "/tmp/old.txt"\n'
        'code_language = "python"\n',
        encoding="utf-8",
    )
    s = TomlSettingsRepository(paths).load()
    assert s == Settings()


def test_malformed_field_value_falls_back_to_default_instead_of_crashing(paths):
    paths.settings_file.write_text(
        'schema_version = 1\nlayout = "qwerty"\ntarget_speed_cpm = "fast"\n',
        encoding="utf-8",
    )
    s = TomlSettingsRepository(paths).load()
    assert s.layout == "qwerty"
    assert s.target_speed_cpm == Settings().target_speed_cpm


def test_malformed_enum_value_falls_back_to_default(paths):
    paths.settings_file.write_text(
        'schema_version = 1\ntarget_speed_unit = "not-a-unit"\n',
        encoding="utf-8",
    )
    s = TomlSettingsRepository(paths).load()
    assert s.target_speed_unit == Settings().target_speed_unit


def test_coerce_field_rejects_non_bool_for_bool_default():
    # bool("false") is True in Python — a quoted-string bool must not be
    # silently coerced, or it would flip the setting instead of falling
    # back to the default via load()'s except (ValueError, TypeError).
    with pytest.raises(TypeError):
        _coerce_field(True, "false")


def test_coerce_field_accepts_real_bool():
    assert _coerce_field(True, False) is False
    assert _coerce_field(False, True) is True
