"""Import a remote word list and persist its URL in settings."""

from __future__ import annotations

from dataclasses import dataclass, replace

from keystrike.domain.protocols import SettingsRepository, WordListStore


class WordListError(Exception):
    """Raised when import or URL validation fails."""


@dataclass(slots=True)
class ImportWordList:
    store: WordListStore
    settings_repo: SettingsRepository

    def __call__(self, url: str) -> int:
        url = url.strip()
        if not url.startswith(("http://", "https://")):
            raise WordListError("URL must start with http:// or https://")
        try:
            words = self.store.download_and_cache(url)
        except ValueError as exc:
            raise WordListError(str(exc)) from exc
        updated = replace(self.settings_repo.load(), wordlist_url=url)
        self.settings_repo.save(updated)
        return len(words)
