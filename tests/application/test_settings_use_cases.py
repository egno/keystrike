import pytest

from keystrike.application.settings_use_cases import (
    CycleLayout,
    SettingsValidationError,
    UpdateSettings,
)
from keystrike.domain.models import Settings
from keystrike.infrastructure.layout_repo import BUNDLED_LAYOUTS
from tests.fakes import FakeLayoutRepository, FakeSettingsRepository


def test_update_settings_persists_all_fields():
    repo = FakeSettingsRepository(Settings())
    update = UpdateSettings(repo=repo)

    result = update(
        layout="dvorak",
        target_speed_cpm=400,
        freeform_path="/tmp/a.txt",
        theme="light",
        alphabet_size=0.75,
        recover_keys=False,
        keyboard_order=True,
    )

    assert result.layout == "dvorak"
    assert result.target_speed_cpm == 400
    assert result.freeform_path == "/tmp/a.txt"
    assert result.theme == "light"
    assert result.alphabet_size == 0.75
    assert result.recover_keys is False
    assert result.keyboard_order is True
    assert repo.settings == result


def test_update_settings_rejects_non_positive_speed():
    repo = FakeSettingsRepository(Settings())
    update = UpdateSettings(repo=repo)

    with pytest.raises(SettingsValidationError):
        update(
            layout="qwerty",
            target_speed_cpm=0,
            freeform_path=None,
            theme="dark",
            alphabet_size=0.5,
            recover_keys=True,
            keyboard_order=False,
        )

    assert repo.settings == Settings()  # unchanged


@pytest.mark.parametrize("alphabet_size", [-0.1, 1.5])
def test_update_settings_rejects_out_of_range_alphabet_size(alphabet_size):
    repo = FakeSettingsRepository(Settings())
    update = UpdateSettings(repo=repo)

    with pytest.raises(SettingsValidationError):
        update(
            layout="qwerty",
            target_speed_cpm=300,
            freeform_path=None,
            theme="dark",
            alphabet_size=alphabet_size,
            recover_keys=True,
            keyboard_order=False,
        )

    assert repo.settings == Settings()  # unchanged


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
