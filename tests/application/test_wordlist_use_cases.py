import pytest

from keystrike.application.wordlist_use_cases import ImportWordList, WordListError
from keystrike.domain.models import Settings
from tests.fakes import FakeSettingsRepository, FakeWordListStore


def test_import_wordlist_downloads_and_persists_url():
    store = FakeWordListStore(by_url={"https://example.com/w.txt": ["cat", "dog"]})
    repo = FakeSettingsRepository(Settings())
    import_wordlist = ImportWordList(store=store, settings_repo=repo)

    count = import_wordlist("https://example.com/w.txt")

    assert count == 2
    assert repo.settings.wordlist_url == "https://example.com/w.txt"


def test_import_wordlist_rejects_non_http_url():
    store = FakeWordListStore()
    repo = FakeSettingsRepository(Settings())
    import_wordlist = ImportWordList(store=store, settings_repo=repo)

    with pytest.raises(WordListError, match="http"):
        import_wordlist("ftp://example.com/w.txt")

    assert repo.settings.wordlist_url == ""


def test_import_wordlist_wraps_download_errors():
    store = FakeWordListStore(download_error=RuntimeError("network down"))
    repo = FakeSettingsRepository(Settings())
    import_wordlist = ImportWordList(store=store, settings_repo=repo)

    with pytest.raises(WordListError, match="network down"):
        import_wordlist("https://example.com/w.txt")

    assert repo.settings.wordlist_url == ""
