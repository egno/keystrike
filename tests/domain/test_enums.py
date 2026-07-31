import pytest

from keystrike.domain.enums import Mode, migrate_legacy_mode


@pytest.mark.parametrize("legacy", ["free", "code", "sample"])
def test_migrate_legacy_mode_maps_retired_modes_to_adaptive(legacy):
    assert migrate_legacy_mode(legacy) is Mode.ADAPTIVE


def test_migrate_legacy_mode_passes_through_current_mode():
    assert migrate_legacy_mode("adaptive") is Mode.ADAPTIVE


def test_migrate_legacy_mode_raises_on_unknown_value():
    with pytest.raises(ValueError, match="not-a-real-mode"):
        migrate_legacy_mode("not-a-real-mode")
