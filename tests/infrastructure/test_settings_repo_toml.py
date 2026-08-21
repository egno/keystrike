from random import Random
from typing import get_args

import pytest

from keystrike.application.build_lesson import BuildLesson
from keystrike.domain.enums import TargetSpeedUnit
from keystrike.domain.models import FocusTuning, Settings, UnlockTuning, WordGenBounds
from keystrike.infrastructure.layout_repo import BUNDLED_LAYOUTS
from keystrike.infrastructure.paths import Paths
from keystrike.infrastructure.settings_repo_toml import (
    _NESTED_TYPES,
    TomlSettingsRepository,
    _coerce_field,
    _NestedTuning,
)
from tests.fakes import (
    FakeAggregatesCache,
    FakeClock,
    FakeLanguageProvider,
    FakeLayoutRepository,
    FakeWordListStore,
)


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


def test_load_generated_word_bounds_from_hand_edited_toml(paths):
    paths.settings_file.write_text(
        "schema_version = 1\n\n[word_gen]\nmin_len = 2\nmax_len = 5\n",
        encoding="utf-8",
    )
    loaded = TomlSettingsRepository(paths).load()
    assert loaded.word_gen.min_len == 2
    assert loaded.word_gen.max_len == 5


def test_toml_generated_word_bounds_affect_markov_lesson_words(paths):
    """Full path: settings.toml → repo.load() → BuildLesson → word lengths."""
    paths.settings_file.write_text(
        'schema_version = 1\nwordlist_url = ""\n\n[word_gen]\nmin_len = 2\nmax_len = 4\n',
        encoding="utf-8",
    )
    builder = BuildLesson(
        layout_repo=FakeLayoutRepository(dict(BUNDLED_LAYOUTS)),
        aggregates_cache=FakeAggregatesCache(),
        settings_repo=TomlSettingsRepository(paths),
        language_provider=FakeLanguageProvider(),
        wordlist_store=FakeWordListStore(),
        rng=Random(0),
        clock=FakeClock(),
    )
    for seed in range(20):
        builder.rng = Random(seed)
        for word in builder("qwerty").text.split():
            assert 2 <= len(word) <= 4, f"seed={seed}: {word!r}"


def test_round_trip(paths):
    repo = TomlSettingsRepository(paths)
    original = Settings(
        layout="dvorak",
        target_speed_cpm=400,
        target_speed_unit=TargetSpeedUnit.WPM,
        alphabet_size=20,
        confidence_session_window=8,
        unlock=UnlockTuning(
            min_confidence_attempts=12,
            min_transition_confidence_attempts=5,
            gating_bigram_limit=3,
            next_letter_unlock_threshold=0.9,
        ),
        focus=FocusTuning(
            char_boost=2.5,
            word_boost=5.0,
            bigram_word_boost=6.0,
            transition_boost=3.5,
            weak_extra_boost=2.0,
            word_min_fraction=0.75,
        ),
        lesson_word_count=15,
        max_word_repeats=3,
        word_gen=WordGenBounds(min_len=2, max_len=5),
    )
    repo.save(original)
    loaded = repo.load()
    assert loaded.layout == original.layout
    assert loaded.target_speed_cpm == original.target_speed_cpm
    assert loaded.confidence_session_window == 8
    assert loaded.unlock == original.unlock
    assert loaded.focus == original.focus
    assert loaded.lesson_word_count == 15
    assert loaded.max_word_repeats == 3
    assert loaded.word_gen == original.word_gen
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


def test_existing_toml_defaults_gating_bigram_limit(paths):
    paths.settings_file.write_text('schema_version = 1\nlayout = "qwerty"\n', encoding="utf-8")
    assert TomlSettingsRepository(paths).load().unlock.gating_bigram_limit == 4


def test_loads_gating_bigram_limit(paths):
    paths.settings_file.write_text(
        "schema_version = 1\n\n[unlock]\ngating_bigram_limit = 2\n",
        encoding="utf-8",
    )
    assert TomlSettingsRepository(paths).load().unlock.gating_bigram_limit == 2


def test_existing_toml_defaults_next_letter_unlock_threshold(paths):
    paths.settings_file.write_text('schema_version = 1\nlayout = "qwerty"\n', encoding="utf-8")
    assert TomlSettingsRepository(paths).load().unlock.next_letter_unlock_threshold == 1.0


def test_loads_next_letter_unlock_threshold(paths):
    paths.settings_file.write_text(
        "schema_version = 1\n\n[unlock]\nnext_letter_unlock_threshold = 0.85\n",
        encoding="utf-8",
    )
    assert TomlSettingsRepository(paths).load().unlock.next_letter_unlock_threshold == 0.85


def test_coerce_field_rejects_non_bool_for_bool_default():
    # bool("false") is True in Python — a quoted-string bool must not be
    # silently coerced, or it would flip the setting instead of falling
    # back to the default via load()'s except (ValueError, TypeError).
    with pytest.raises(TypeError):
        _coerce_field(True, "false")


def test_coerce_field_accepts_real_bool():
    assert _coerce_field(True, False) is False
    assert _coerce_field(False, True) is True


def test_coerce_field_rejects_bool_for_int_default():
    # bool is an int subclass -- int(True) == 1 would otherwise silently
    # coerce a stray `alphabet_size = true` instead of falling back to
    # the default via load()'s except (ValueError, TypeError).
    with pytest.raises(TypeError):
        _coerce_field(16, True)


def test_settings_file_with_control_chars_round_trips(paths):
    """Regression: an unescaped control char in a written string value used
    to corrupt the TOML file, which load() then silently replaced with
    Settings() -- reverting every setting, not just the offending field."""
    repo = TomlSettingsRepository(paths)
    original = Settings(
        wordlist_url='https://example.com/a"b\nc',
        unlock=UnlockTuning(next_letter_unlock_threshold=0.75),
    )
    repo.save(original)
    loaded = repo.load()
    assert loaded.wordlist_url == original.wordlist_url
    assert loaded.unlock.next_letter_unlock_threshold == 0.75


def test_nested_types_matches_nested_tuning_union():
    """`_NESTED_TYPES` is a literal tuple (not derived from `_NestedTuning`
    via `typing.get_args`) so pyright can narrow `isinstance` checks on it --
    this guards the two from drifting apart instead."""
    assert set(_NESTED_TYPES) == set(get_args(_NestedTuning))
