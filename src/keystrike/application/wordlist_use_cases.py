"""Import a remote word list and query cache status."""

from __future__ import annotations

from dataclasses import dataclass, replace

from keystrike.domain.protocols import SettingsRepository, WordListStore

DEFAULT_WORDLIST_URL = (
    "https://raw.githubusercontent.com/first20hours/google-10000-english/"
    "master/google-10000-english-usa-no-swears.txt"
)


class WordListError(Exception):
    """Raised when import or URL validation fails."""


def validate_wordlist_url(url: str) -> None:
    stripped = url.strip()
    if stripped and not stripped.startswith(("http://", "https://")):
        raise WordListError("URL must start with http:// or https://")


@dataclass(slots=True)
class ImportWordList:
    store: WordListStore
    settings_repo: SettingsRepository

    def __call__(self, url: str) -> int:
        url = url.strip()
        if not url:
            url = DEFAULT_WORDLIST_URL
        validate_wordlist_url(url)
        try:
            words = self.store.download_and_cache(url)
        except Exception as exc:
            raise WordListError(str(exc)) from exc
        updated = replace(self.settings_repo.load(), wordlist_url=url)
        self.settings_repo.save(updated)
        return len(words)


@dataclass(slots=True)
class ClearWordList:
    settings_repo: SettingsRepository

    def __call__(self) -> None:
        updated = replace(self.settings_repo.load(), wordlist_url="")
        self.settings_repo.save(updated)


@dataclass(slots=True)
class GetWordListCacheStatus:
    store: WordListStore

    def __call__(self, url: str) -> int | None:
        return self.store.cached_word_count(url.strip())
