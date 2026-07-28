"""Download, cache, and load user word lists on disk."""

from __future__ import annotations

import hashlib
import urllib.error
import urllib.request

from keystrike.domain.wordlist import parse_wordlist_text

from .atomic_write import atomic_write_text
from .paths import Paths

MAX_DOWNLOAD_BYTES = 5 * 1024 * 1024
_USER_AGENT = "keystrike/0.1"
_READ_CHUNK = 65536


class FileWordListStore:
    def __init__(self, paths: Paths) -> None:
        self._paths = paths

    def load(self, url: str) -> list[str] | None:
        path = self._paths.cache_dir / self._cache_name(url)
        if not path.exists():
            return None
        return parse_wordlist_text(path.read_text(encoding="utf-8", errors="ignore"))

    def cached_word_count(self, url: str) -> int | None:
        words = self.load(url)
        return len(words) if words is not None else None

    def download_and_cache(self, url: str) -> list[str]:
        text = _download_text(url, MAX_DOWNLOAD_BYTES)
        words = parse_wordlist_text(text)
        if not words:
            raise ValueError("no usable words in downloaded list")
        path = self._paths.cache_dir / self._cache_name(url)
        atomic_write_text(path, text)
        return words

    def _cache_name(self, url: str) -> str:
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:12]
        return f"wordlist-{digest}.txt"


def _download_text(url: str, max_bytes: int) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            chunks: list[bytes] = []
            total = 0
            while True:
                chunk = resp.read(_READ_CHUNK)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise ValueError(f"download exceeds {max_bytes} bytes")
                chunks.append(chunk)
    except urllib.error.URLError as exc:
        raise ValueError(str(exc.reason or exc)) from exc
    return b"".join(chunks).decode("utf-8", errors="ignore")
