import json

import pytest

from keystrike.domain.confidence import target_ms_per_char, transition_confidence_of
from keystrike.domain.models import Bigram, KeyStats, LayoutAggregates, TransitionStats
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
        ord("a"): KeyStats(ord("a"), 10, 120_000_000.0, 1, 1_700_000_000.0, attempt_count=11),
        ord("b"): KeyStats(ord("b"), 5, 200_000_000.0, 3, 1_700_000_100.0, attempt_count=8),
    }
    transitions = {
        Bigram(ord("a"), ord("b")): TransitionStats(
            ord("a"),
            ord("b"),
            4,
            150_000_000.0,
            2,
            1_700_000_050.0,
            attempt_count=6,
        ),
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


def test_put_strips_same_key_transitions(paths):
    cache = FileAggregatesCache(paths)
    aggregates = LayoutAggregates(
        keys={ord("a"): KeyStats(ord("a"), 1, 100.0, 0, 1.0)},
        transitions={
            Bigram(ord("a"), ord("a")): TransitionStats(ord("a"), ord("a"), 1, 100.0, 0, 1.0),
            Bigram(ord("a"), ord("b")): TransitionStats(ord("a"), ord("b"), 1, 100.0, 0, 1.0),
        },
    )
    cache.put("qwerty", aggregates)
    loaded = cache.get("qwerty")
    assert loaded is not None
    assert Bigram(ord("a"), ord("a")) not in loaded.transitions
    assert Bigram(ord("a"), ord("b")) in loaded.transitions
    raw = json.loads(cache._file("qwerty").read_text(encoding="utf-8"))
    assert "aa" not in raw["transitions"]


def test_get_strips_same_key_transitions_from_stale_cache(paths):
    cache = FileAggregatesCache(paths)
    cache._file("qwerty").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "layout": "qwerty",
                "keys": {},
                "transitions": {
                    "aa": {
                        "prev_cp": ord("a"),
                        "next_cp": ord("a"),
                        "samples": 1,
                        "mean_time_ns": 100.0,
                        "error_count": 0,
                        "last_seen": 1.0,
                        "attempt_count": 1,
                    },
                    "ab": {
                        "prev_cp": ord("a"),
                        "next_cp": ord("b"),
                        "samples": 1,
                        "mean_time_ns": 100.0,
                        "error_count": 0,
                        "last_seen": 1.0,
                        "attempt_count": 1,
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    loaded = cache.get("qwerty")
    assert loaded is not None
    assert Bigram(ord("a"), ord("a")) not in loaded.transitions
    assert Bigram(ord("a"), ord("b")) in loaded.transitions


def test_get_repairs_zero_samples_when_mean_time_present(paths):
    """Pre-fix cache wrote samples=0 while mean_time_ns stayed measured."""
    cache = FileAggregatesCache(paths)
    cache._file("qwerty").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "layout": "qwerty",
                "keys": {},
                "transitions": {
                    "eo": {
                        "prev_cp": ord("e"),
                        "next_cp": ord("o"),
                        "samples": 0,
                        "mean_time_ns": 196_000_000.0,
                        "error_count": 0,
                        "last_seen": 1.0,
                        "attempt_count": 0,
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    loaded = cache.get("qwerty")
    assert loaded is not None
    eo = loaded.transitions[Bigram(ord("e"), ord("o"))]
    assert eo.samples == 1
    assert eo.attempt_count == 1
    assert (
        transition_confidence_of(
            ord("e"),
            ord("o"),
            loaded.transitions,
            target_ms_per_char(300),
        )
        > 0.0
    )


def test_get_repairs_zero_attempt_count_when_samples_present(paths):
    """Pre-fix cache wrote attempt_count=0 while samples stayed > 0."""
    cache = FileAggregatesCache(paths)
    cache._file("qwerty").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "layout": "qwerty",
                "keys": {},
                "transitions": {
                    "eo": {
                        "prev_cp": ord("e"),
                        "next_cp": ord("o"),
                        "samples": 1,
                        "mean_time_ns": 196_000_000.0,
                        "error_count": 0,
                        "last_seen": 1.0,
                        "attempt_count": 0,
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    loaded = cache.get("qwerty")
    assert loaded is not None
    eo = loaded.transitions[Bigram(ord("e"), ord("o"))]
    assert eo.attempt_count == 1

    assert (
        transition_confidence_of(
            ord("e"),
            ord("o"),
            loaded.transitions,
            target_ms_per_char(300),
        )
        > 0.0
    )
