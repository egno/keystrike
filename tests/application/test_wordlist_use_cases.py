import pytest

from keystrike.application.wordlist_use_cases import (
    DEFAULT_WORDLIST_URL,
    ClearWordList,
    GetWordListCacheStatus,
    ImportWordList,
    WordListError,
)
from keystrike.domain.models import Settings
from tests.fakes import FakeSettingsRepository, FakeWordListStore


def test_import_wordlist_downloads_and_persists_url():
    store = FakeWordListStore(by_url={"https://example.com/w.txt": ["cat", "dog"]})
    repo = FakeSettingsRepository(Settings())
    import_wordlist = ImportWordList(store=store, settings_repo=repo)

    count = import_wordlist("https://example.com/w.txt")

    assert count == 2
    assert repo.settings.wordlist_url == "https://example.com/w.txt"


def test_import_wordlist_uses_default_url_when_empty():
    store = FakeWordListStore(by_url={DEFAULT_WORDLIST_URL: ["hello", "world"]})
    repo = FakeSettingsRepository(Settings())
    import_wordlist = ImportWordList(store=store, settings_repo=repo)

    count = import_wordlist("")

    assert count == 2
    assert repo.settings.wordlist_url == DEFAULT_WORDLIST_URL


def test_import_wordlist_rejects_non_http_url():
    store = FakeWordListStore()
    repo = FakeSettingsRepository(Settings())
    import_wordlist = ImportWordList(store=store, settings_repo=repo)

    with pytest.raises(WordListError, match="http"):
        import_wordlist("ftp://example.com/w.txt")

    assert repo.settings.wordlist_url == ""


def test_import_wordlist_wraps_download_errors():
    # FakeWordListStore raises RuntimeError (not ValueError) to verify wrapping.
    store = FakeWordListStore(download_error=RuntimeError("network down"))
    repo = FakeSettingsRepository(Settings())
    import_wordlist = ImportWordList(store=store, settings_repo=repo)

    with pytest.raises(WordListError, match="network down"):
        import_wordlist("https://example.com/w.txt")

    assert repo.settings.wordlist_url == ""


def test_clear_wordlist_clears_persisted_url():
    url = "https://example.com/w.txt"
    repo = FakeSettingsRepository(Settings(wordlist_url=url))
    clear = ClearWordList(settings_repo=repo)

    clear()

    assert repo.settings.wordlist_url == ""


def test_get_wordlist_cache_status_returns_count_or_none():
    url = "https://example.com/w.txt"
    store = FakeWordListStore(by_url={url: ["cat", "dog", "bat"]})
    status = GetWordListCacheStatus(store=store)

    assert status(url) == 3
    assert status("https://example.com/missing.txt") is None
