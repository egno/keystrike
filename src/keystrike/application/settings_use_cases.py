"""Use cases for reading and mutating persisted Settings.

Screens read Settings directly via SettingsRepository (that's a plain read,
not a business decision) but every *write* — validation included — goes
through one of these, so the business rules aren't duplicated across screens.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from keystrike.domain.enums import TargetSpeedUnit
from keystrike.domain.models import Settings
from keystrike.domain.protocols import LayoutRepository, SettingsRepository

_MIN_LAYOUTS_TO_CYCLE = 2


class SettingsValidationError(ValueError):
    """Raised by UpdateSettings when a proposed change is invalid."""


@dataclass(slots=True)
class UpdateSettings:
    repo: SettingsRepository

    def __call__(
        self,
        *,
        layout: str,
        target_speed_cpm: int,
        target_speed_unit: TargetSpeedUnit,
        alphabet_size: int,
        learn_daily_minutes: int,
        wordlist_url: str = "",
    ) -> Settings:
        if target_speed_cpm <= 0:
            raise SettingsValidationError("Target speed must be a positive integer.")
        if target_speed_unit not in TargetSpeedUnit:
            raise SettingsValidationError("Target speed unit must be wpm or cpm.")
        if alphabet_size < 0:
            raise SettingsValidationError("Number of letters must be zero or more.")
        if learn_daily_minutes < 0:
            raise SettingsValidationError("Daily learn minutes must be zero or more.")
        updated = replace(
            self.repo.load(),
            layout=layout,
            target_speed_cpm=target_speed_cpm,
            target_speed_unit=target_speed_unit,
            alphabet_size=alphabet_size,
            learn_daily_minutes=learn_daily_minutes,
            wordlist_url=wordlist_url.strip(),
        )
        self.repo.save(updated)
        return updated


@dataclass(slots=True)
class CycleLayout:
    """Advance to the next available layout (wrapping) and persist it.
    A no-op if fewer than two layouts are available."""

    settings_repo: SettingsRepository
    layout_repo: LayoutRepository

    def __call__(self) -> Settings:
        available = self.layout_repo.list_available()
        current = self.settings_repo.load()
        if len(available) < _MIN_LAYOUTS_TO_CYCLE:
            return current

        current_index = available.index(current.layout) if current.layout in available else -1
        next_layout = available[(current_index + 1) % len(available)]
        updated = replace(current, layout=next_layout)
        self.settings_repo.save(updated)
        return updated
