"""Keep `Settings.alphabet_size` in lockstep with the live unlocked-key count.

`compute_unlocked` (see `domain.unlock`) treats `alphabet_size` as a floor: once
every currently-unlocked key clears its mastery threshold, it force-unlocks
further keys from `learn_order` without touching `Settings`. Left alone, that
means a lesson can show more letters than Settings reports. `sync_alphabet_size`
closes that gap by persisting the higher count as soon as it's discovered --
before anything downstream builds a lesson or reports progress off the stale
value.
"""

from __future__ import annotations

from dataclasses import replace

from keystrike.domain.models import Settings
from keystrike.domain.protocols import SettingsRepository


def sync_alphabet_size(
    settings: Settings,
    unlocked_keys: tuple[int, ...],
    settings_repo: SettingsRepository,
) -> Settings:
    """Bump `settings.alphabet_size` up to `len(unlocked_keys)` and persist
    it, if that's larger. `unlocked_keys` must have been computed with
    `settings.alphabet_size` as its floor (e.g. via `compute_unlocked`)."""
    unlocked_count = len(unlocked_keys)
    if unlocked_count <= settings.alphabet_size:
        return settings
    updated = replace(settings, alphabet_size=unlocked_count)
    settings_repo.save(updated)
    return updated
