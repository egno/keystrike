import hashlib

import pytest

from keystrike.infrastructure.paths import Paths
from keystrike.infrastructure.wordlist_store import MAX_DOWNLOAD_BYTES, FileWordListStore


@pytest.fixture
def paths(tmp_path):
    p = Paths(
        config_dir=tmp_path / "config",
        data_dir=tmp_path / "data",
        log_dir=tmp_path / "logs",
    )
    p.cache_dir.mkdir(parents=True, exist_ok=True)
    return p


def test_load_returns_none_when_missing(paths):
    assert FileWordListStore(paths).load("https://example.com/words.txt") is None


def test_download_and_cache_then_load(paths, monkeypatch):
    url = "https://example.com/words.txt"
    body = "cat\ndog\nbird\n"

    class FakeResponse:
        _data = body.encode()
        _pos = 0

        def read(self, size: int) -> bytes:
            chunk = self._data[self._pos : self._pos + size]
            self._pos += len(chunk)
            return chunk

        def __enter__(self):
            return self

        def __exit__(self, *args: object) -> None:
            pass

    monkeypatch.setattr(
        "keystrike.infrastructure.wordlist_store.urllib.request.urlopen",
        lambda *args, **kwargs: FakeResponse(),
    )

    store = FileWordListStore(paths)
    words = store.download_and_cache(url)
    assert words == ["cat", "dog", "bird"]
    assert store.cached_word_count(url) == 3

    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:12]
    cache_file = paths.cache_dir / f"wordlist-{digest}.txt"
    assert cache_file.exists()
    assert store.load(url) == words


def test_download_rejects_oversized(paths, monkeypatch):
    url = "https://example.com/huge.txt"

    class FakeResponse:
        def read(self, size: int) -> bytes:
            return b"x" * (MAX_DOWNLOAD_BYTES + 1)

        def __enter__(self):
            return self

        def __exit__(self, *args: object) -> None:
            pass

    monkeypatch.setattr(
        "keystrike.infrastructure.wordlist_store.urllib.request.urlopen",
        lambda *args, **kwargs: FakeResponse(),
    )

    with pytest.raises(ValueError, match="exceeds"):
        FileWordListStore(paths).download_and_cache(url)


def test_download_rejects_empty_usable_words(paths, monkeypatch):
    url = "https://example.com/bad.txt"

    class FakeResponse:
        _data = b"123\nUPPER\n"
        _pos = 0

        def read(self, size: int) -> bytes:
            chunk = self._data[self._pos : self._pos + size]
            self._pos += len(chunk)
            return chunk

        def __enter__(self):
            return self

        def __exit__(self, *args: object) -> None:
            pass

    monkeypatch.setattr(
        "keystrike.infrastructure.wordlist_store.urllib.request.urlopen",
        lambda *args, **kwargs: FakeResponse(),
    )

    with pytest.raises(ValueError, match="no usable words"):
        FileWordListStore(paths).download_and_cache(url)
