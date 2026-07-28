import pytest

from keystrike.domain.models import KeyStats
from keystrike.infrastructure.aggregates_cache import FileAggregatesCache
from keystrike.infrastructure.paths import Paths


@pytest.fixture
def paths(tmp_path):
    p = Paths(
        config_dir=tmp_path / "config",
        data_dir=tmp_path / "data",
        log_dir=tmp_path / "logs",
    )
    p.cache_dir.mkdir(parents=True, exist_ok=True)
    return p


def test_get_returns_none_when_missing(paths):
    assert FileAggregatesCache(paths).get("qwerty") is None


def test_put_then_get(paths):
    cache = FileAggregatesCache(paths)
    stats = {
        ord("a"): KeyStats(ord("a"), 10, 120_000_000.0, 1, 1_700_000_000.0, 0.85),
        ord("b"): KeyStats(ord("b"), 5, 200_000_000.0, 3, 1_700_000_100.0, 0.60),
    }
    cache.put("qwerty", stats)
    loaded = cache.get("qwerty")
    assert loaded == stats


def test_layout_isolation(paths):
    cache = FileAggregatesCache(paths)
    cache.put("qwerty", {ord("a"): KeyStats(ord("a"), 1, 100.0, 0, 1.0, 0.0)})
    cache.put("dvorak", {ord("z"): KeyStats(ord("z"), 2, 50.0, 0, 2.0, 0.0)})
    qwerty = cache.get("qwerty")
    dvorak = cache.get("dvorak")
    assert qwerty is not None
    assert dvorak is not None
    assert ord("a") in qwerty
    assert ord("z") in dvorak
    assert ord("z") not in qwerty
