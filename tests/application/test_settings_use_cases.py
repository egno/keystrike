import pytest

from keystrike.application.settings_use_cases import (
    CycleLayout,
    SettingsValidationError,
    UpdateSettings,
)
from keystrike.domain.enums import TargetSpeedUnit
from keystrike.domain.models import Settings
from keystrike.infrastructure.layout_repo import BUNDLED_LAYOUTS
from tests.fakes import FakeLayoutRepository, FakeSettingsRepository


def test_update_settings_persists_all_fields():
    repo = FakeSettingsRepository(Settings())
    update = UpdateSettings(repo=repo)

    result = update(
        layout="dvorak",
        target_speed_cpm=400,
        target_speed_unit=TargetSpeedUnit.WPM,
        alphabet_size=20,
        learn_daily_minutes=15,
        confidence_session_window=10,
        min_confidence_attempts=10,
        min_transition_confidence_attempts=4,
    )

    assert result.layout == "dvorak"
    assert result.target_speed_cpm == 400
    assert result.target_speed_unit == TargetSpeedUnit.WPM
    assert result.alphabet_size == 20
    assert result.learn_daily_minutes == 15
    assert result.confidence_session_window == 10
    assert result.min_confidence_attempts == 10
    assert result.min_transition_confidence_attempts == 4
    assert result.wordlist_url == ""
    assert repo.settings == result


def test_update_settings_rejects_non_positive_speed():
    repo = FakeSettingsRepository(Settings())
    update = UpdateSettings(repo=repo)

    with pytest.raises(SettingsValidationError):
        update(
            layout="qwerty",
            target_speed_cpm=0,
            target_speed_unit=TargetSpeedUnit.CPM,
            alphabet_size=16,
            learn_daily_minutes=10,
            confidence_session_window=10,
            min_confidence_attempts=10,
            min_transition_confidence_attempts=4,
        )

    assert repo.settings == Settings()  # unchanged


def test_update_settings_rejects_negative_alphabet_size():
    repo = FakeSettingsRepository(Settings())
    update = UpdateSettings(repo=repo)

    with pytest.raises(SettingsValidationError):
        update(
            layout="qwerty",
            target_speed_cpm=300,
            target_speed_unit=TargetSpeedUnit.CPM,
            alphabet_size=-1,
            learn_daily_minutes=10,
            confidence_session_window=10,
            min_confidence_attempts=10,
            min_transition_confidence_attempts=4,
        )

    assert repo.settings == Settings()  # unchanged


def test_update_settings_rejects_negative_learn_daily_minutes():
    repo = FakeSettingsRepository(Settings())
    update = UpdateSettings(repo=repo)

    with pytest.raises(SettingsValidationError):
        update(
            layout="qwerty",
            target_speed_cpm=300,
            target_speed_unit=TargetSpeedUnit.CPM,
            alphabet_size=16,
            learn_daily_minutes=-1,
            confidence_session_window=10,
            min_confidence_attempts=10,
            min_transition_confidence_attempts=4,
        )

    assert repo.settings == Settings()


def test_update_settings_rejects_invalid_confidence_session_window():
    repo = FakeSettingsRepository(Settings())
    update = UpdateSettings(repo=repo)

    with pytest.raises(SettingsValidationError):
        update(
            layout="qwerty",
            target_speed_cpm=300,
            target_speed_unit=TargetSpeedUnit.CPM,
            alphabet_size=16,
            learn_daily_minutes=10,
            confidence_session_window=0,
            min_confidence_attempts=10,
            min_transition_confidence_attempts=4,
        )

    assert repo.settings == Settings()


def test_update_settings_rejects_invalid_min_confidence_attempts():
    repo = FakeSettingsRepository(Settings())
    update = UpdateSettings(repo=repo)

    with pytest.raises(SettingsValidationError):
        update(
            layout="qwerty",
            target_speed_cpm=300,
            target_speed_unit=TargetSpeedUnit.CPM,
            alphabet_size=16,
            learn_daily_minutes=10,
            confidence_session_window=10,
            min_confidence_attempts=0,
            min_transition_confidence_attempts=4,
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
