from keystrike.application.alphabet_sync import sync_alphabet_size
from keystrike.domain.models import Settings
from tests.fakes import FakeSettingsRepository


def test_sync_alphabet_size_is_noop_when_unlocked_not_larger():
    settings = Settings(alphabet_size=5)
    repo = FakeSettingsRepository(settings)

    result = sync_alphabet_size(settings, (1, 2, 3), repo)

    assert result is settings
    assert repo.settings is settings


def test_sync_alphabet_size_is_noop_when_unlocked_equals_setting():
    settings = Settings(alphabet_size=3)
    repo = FakeSettingsRepository(settings)

    result = sync_alphabet_size(settings, (1, 2, 3), repo)

    assert result is settings
    assert repo.settings is settings


def test_sync_alphabet_size_bumps_and_persists_when_unlocked_grows():
    settings = Settings(alphabet_size=2)
    repo = FakeSettingsRepository(settings)

    result = sync_alphabet_size(settings, (1, 2, 3, 4), repo)

    assert result.alphabet_size == 4
    assert repo.settings.alphabet_size == 4
    assert repo.settings is result


def test_sync_alphabet_size_preserves_other_fields_on_bump():
    settings = Settings(alphabet_size=2, target_speed_cpm=250)
    repo = FakeSettingsRepository(settings)

    result = sync_alphabet_size(settings, (1, 2, 3), repo)

    assert result.target_speed_cpm == 250


def test_sync_alphabet_size_is_noop_on_empty_unlocked():
    settings = Settings(alphabet_size=5)
    repo = FakeSettingsRepository(settings)

    result = sync_alphabet_size(settings, (), repo)

    assert result is settings
    assert repo.settings is settings
