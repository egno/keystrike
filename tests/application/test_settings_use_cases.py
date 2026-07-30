import pytest

from keystrike.application.settings_use_cases import (
    CycleLayout,
    SettingsUpdate,
    SettingsValidationError,
    UpdateSettings,
)
from keystrike.domain.enums import TargetSpeedUnit
from keystrike.domain.models import Settings
from keystrike.infrastructure.layout_repo import BUNDLED_LAYOUTS, CompositeLayoutRepository
from keystrike.infrastructure.paths import Paths
from tests.fakes import FakeLayoutRepository, FakeSettingsRepository


@pytest.fixture
def paths(tmp_path):
    return Paths(
        config_dir=tmp_path / "config",
        data_dir=tmp_path / "data",
        log_dir=tmp_path / "log",
    )


def test_update_settings_persists_all_fields():
    repo = FakeSettingsRepository(Settings())
    update = UpdateSettings(repo=repo)

    result = update(
        SettingsUpdate(
            layout="dvorak",
            target_speed_cpm=400,
            target_speed_unit=TargetSpeedUnit.WPM,
            alphabet_size=20,
            learn_daily_minutes=15,
        ),
    )

    assert result.layout == "dvorak"
    assert result.target_speed_cpm == 400
    assert result.target_speed_unit == TargetSpeedUnit.WPM
    assert result.alphabet_size == 20
    assert result.learn_daily_minutes == 15
    assert result.confidence_session_window == Settings().confidence_session_window
    assert result.min_confidence_attempts == Settings().min_confidence_attempts
    assert result.min_transition_confidence_attempts == (
        Settings().min_transition_confidence_attempts
    )
    assert result.wordlist_url == ""
    assert repo.settings == result


def test_update_settings_preserves_confidence_fields_from_repo():
    repo = FakeSettingsRepository(
        Settings(
            confidence_session_window=8,
            min_confidence_attempts=12,
            min_transition_confidence_attempts=5,
        ),
    )
    update = UpdateSettings(repo=repo)

    result = update(
        SettingsUpdate(
            layout="qwerty",
            target_speed_cpm=300,
            target_speed_unit=TargetSpeedUnit.CPM,
            alphabet_size=16,
            learn_daily_minutes=10,
        ),
    )

    assert result.confidence_session_window == 8
    assert result.min_confidence_attempts == 12
    assert result.min_transition_confidence_attempts == 5


def test_update_settings_rejects_non_positive_speed():
    repo = FakeSettingsRepository(Settings())
    update = UpdateSettings(repo=repo)

    with pytest.raises(SettingsValidationError):
        update(
            SettingsUpdate(
                layout="qwerty",
                target_speed_cpm=0,
                target_speed_unit=TargetSpeedUnit.CPM,
                alphabet_size=16,
                learn_daily_minutes=10,
            ),
        )

    assert repo.settings == Settings()  # unchanged


def test_update_settings_rejects_negative_alphabet_size():
    repo = FakeSettingsRepository(Settings())
    update = UpdateSettings(repo=repo)

    with pytest.raises(SettingsValidationError):
        update(
            SettingsUpdate(
                layout="qwerty",
                target_speed_cpm=300,
                target_speed_unit=TargetSpeedUnit.CPM,
                alphabet_size=-1,
                learn_daily_minutes=10,
            ),
        )

    assert repo.settings == Settings()  # unchanged


def test_update_settings_rejects_negative_learn_daily_minutes():
    repo = FakeSettingsRepository(Settings())
    update = UpdateSettings(repo=repo)

    with pytest.raises(SettingsValidationError):
        update(
            SettingsUpdate(
                layout="qwerty",
                target_speed_cpm=300,
                target_speed_unit=TargetSpeedUnit.CPM,
                alphabet_size=16,
                learn_daily_minutes=-1,
            ),
        )

    assert repo.settings == Settings()


def test_cycle_layout_advances_and_wraps():
    repo = FakeSettingsRepository(Settings(layout="qwerty"))
    layout_repo = FakeLayoutRepository(dict(BUNDLED_LAYOUTS))
    cycle = CycleLayout(settings_repo=repo, layout_repo=layout_repo)

    # list_available() is sorted: colemak, colemak_dh, dvorak, qwerty.
    assert cycle().layout == "colemak"
    assert cycle().layout == "colemak_dh"
    assert cycle().layout == "dvorak"
    assert cycle().layout == "qwerty"


def test_cycle_layout_noop_with_fewer_than_two_layouts():
    repo = FakeSettingsRepository(Settings(layout="qwerty"))
    layout_repo = FakeLayoutRepository({"qwerty": BUNDLED_LAYOUTS["qwerty"]})
    cycle = CycleLayout(settings_repo=repo, layout_repo=layout_repo)

    result = cycle()

    assert result.layout == "qwerty"


def test_cycle_layout_includes_custom_toml_layout(paths):
    paths.layouts_dir.mkdir(parents=True)
    (paths.layouts_dir / "myown.toml").write_text(
        'name = "myown"\nlearn_order = "a"\n\n'
        '[[keys]]\nchar = "a"\nrow = 1\ncol = 0\nfinger = "PINKY"\nhand = "L"\n',
        encoding="utf-8",
    )
    layout_repo = CompositeLayoutRepository(paths)
    repo = FakeSettingsRepository(Settings(layout="qwerty"))
    cycle = CycleLayout(settings_repo=repo, layout_repo=layout_repo)

    layouts_seen = {cycle().layout for _ in range(len(layout_repo.list_available()))}

    assert "myown" in layouts_seen
    assert layouts_seen == set(layout_repo.list_available())
