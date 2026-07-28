import pytest

from keystrike.domain.models import KeyStats, LayoutAggregates, TransitionStats
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
        ord("a"): KeyStats(ord("a"), 10, 120_000_000.0, 1, 1_700_000_000.0),
        ord("b"): KeyStats(ord("b"), 5, 200_000_000.0, 3, 1_700_000_100.0),
    }
    transitions = {
        "ab": TransitionStats(ord("a"), ord("b"), 4, 150_000_000.0, 2, 1_700_000_050.0),
    }
    aggregates = LayoutAggregates(keys=stats, transitions=transitions)
    cache.put("qwerty", aggregates)
    loaded = cache.get("qwerty")
    assert loaded == aggregates


def test_get_old_cache_without_transitions(paths):
    cache = FileAggregatesCache(paths)
    cache.put("qwerty", LayoutAggregates(keys={ord("a"): KeyStats(ord("a"), 1, 100.0, 0, 1.0)}))
    loaded = cache.get("qwerty")
    assert loaded is not None
    assert loaded.transitions == {}


def test_layout_isolation(paths):
    cache = FileAggregatesCache(paths)
    cache.put("qwerty", LayoutAggregates(keys={ord("a"): KeyStats(ord("a"), 1, 100.0, 0, 1.0)}))
    cache.put("dvorak", LayoutAggregates(keys={ord("z"): KeyStats(ord("z"), 2, 50.0, 0, 2.0)}))
    qwerty = cache.get("qwerty")
    dvorak = cache.get("dvorak")
    assert qwerty is not None
    assert dvorak is not None
    assert ord("a") in qwerty.keys
    assert ord("z") in dvorak.keys
    assert ord("z") not in qwerty.keys
