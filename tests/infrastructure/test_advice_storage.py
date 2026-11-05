from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from keystrike.domain.advice import (
    DEFAULT_RECENCY_DECAY,
    AdvisorConfig,
    Evidence,
    Kind,
    LessonAdvice,
)
from keystrike.infrastructure.advice_store import FileAdviceStore
from keystrike.infrastructure.advisor_config_toml import TomlAdvisorConfigRepository
from keystrike.infrastructure.paths import Paths
from keystrike.infrastructure.sync_git import _SYNC_REL_PATHS  # pyright: ignore[reportPrivateUsage]
from tests.advice_helpers import advice, rec


@pytest.fixture
def paths(tmp_path: Path) -> Paths:
    return Paths(config_dir=tmp_path / "cfg", data_dir=tmp_path / "data", log_dir=tmp_path / "log")


def test_config_default_is_the_rules_advisor(paths: Paths):
    assert TomlAdvisorConfigRepository(paths).load() == AdvisorConfig(active="rules")


def test_config_round_trip(paths: Paths):
    repo = TomlAdvisorConfigRepository(paths)
    config = AdvisorConfig(
        active="llm",
        confirmed_off_device=("llm",),
        sections={"llm": {"provider": "openai", "model": 'm "x"', "endpoint": "http://h:1/v1"}},
    )
    repo.save(config)
    assert repo.load() == config


def test_config_is_not_synced(paths: Paths):
    synced = {paths.config_dir / rel for rel in _SYNC_REL_PATHS}
    assert paths.advisors_file not in synced
    assert paths.advisors_file.parent == paths.config_dir


def test_a_bad_file_falls_back_to_the_default(paths: Paths):
    paths.config_dir.mkdir(parents=True)
    paths.advisors_file.write_text("not = [toml", encoding="utf-8")
    assert TomlAdvisorConfigRepository(paths).load() == AdvisorConfig(active="rules")


def test_non_string_values_are_ignored(paths: Paths):
    paths.config_dir.mkdir(parents=True)
    paths.advisors_file.write_text(
        'active = "llm"\nconfirmed_off_device = ["llm", 3]\n[llm]\nmodel = "m"\nretries = 3\n',
        encoding="utf-8",
    )
    config = TomlAdvisorConfigRepository(paths).load()
    assert config.confirmed_off_device == ("llm",)
    assert config.section("llm") == {"model": "m"}


def test_old_ai_coach_config_is_read_once_as_the_llm_advisor(paths: Paths):
    paths.config_dir.mkdir(parents=True)
    paths.ai_settings_file.write_text(
        'provider = "ollama"\nmodel = "qwen"\nendpoint = "http://box:11434"\n', encoding="utf-8"
    )
    repo = TomlAdvisorConfigRepository(paths)
    config = repo.load()
    assert config.active == "llm"
    assert config.confirmed_off_device == ("llm",)  # the user already opted in
    assert config.section("llm") == {
        "provider": "ollama",
        "model": "qwen",
        "endpoint": "http://box:11434",
    }
    repo.save(AdvisorConfig(active="rules"))
    assert repo.load().active == "rules"  # advisors.toml wins from now on


def test_old_ai_coach_that_was_off_gets_the_default_advisor(paths: Paths):
    paths.config_dir.mkdir(parents=True)
    paths.ai_settings_file.write_text('provider = ""\nmodel = "m"\n', encoding="utf-8")
    config = TomlAdvisorConfigRepository(paths).load()
    assert config.active == "rules"
    assert config.confirmed_off_device == ()


def test_store_round_trip_per_layout_and_advisor(paths: Paths):
    store = FileAdviceStore(paths)
    assert store.get("qwerty", "rules") is None
    stored = advice(
        rec(Kind.FOCUS, 115, events=3, opportunities=40),
        rec(Kind.CONTRAST, 101, 105, strength=0.8, events=2),
        rec(Kind.EASE, 97, 111),
        source="rules",
        summary="Slow on s",
    )
    stored = replace(stored, created_at=12.5)
    other = advice(rec(Kind.EMPHASIZE, 101), source="llm")
    store.put("qwerty", stored)
    store.put("qwerty", other)
    store.put("colemak", advice(rec(Kind.FOCUS, 99), source="rules"))
    fresh = FileAdviceStore(paths)
    assert fresh.get("qwerty", "rules") == stored  # including evidence and applied
    assert fresh.get("qwerty", "llm") == other
    assert fresh.get("colemak", "rules") is not None
    assert fresh.get("colemak", "llm") is None


def test_store_ignores_failures_and_unbound_advice_and_clears(paths: Paths):
    store = FileAdviceStore(paths)
    store.put("qwerty", LessonAdvice(source="rules", error="boom"))
    store.put("qwerty", advice(rec(Kind.FOCUS, 97)))  # no source
    assert store.get("qwerty", "rules") is None
    store.put("qwerty", advice(rec(Kind.FOCUS, 97), source="rules"))
    store.clear()
    assert store.get("qwerty", "rules") is None


def test_a_row_of_the_old_format_is_ignored_until_the_next_advice_replaces_it(paths: Paths):
    paths.cache_dir.mkdir(parents=True)
    paths.advice_file.write_text(
        '{"qwerty": {"rules": {"summary": "old", "focus_key": 97, "emphasis_keys": [101],'
        ' "rest_keys": [], "focus_pair": null, "created_at": 5.0}}}',
        encoding="utf-8",
    )
    store = FileAdviceStore(paths)
    assert store.get("qwerty", "rules") is None
    store.put("qwerty", advice(rec(Kind.FOCUS, 99), source="rules"))
    assert store.get("qwerty", "rules") is not None


def test_unknown_kinds_and_reasons_in_a_row_are_skipped(paths: Paths):
    paths.cache_dir.mkdir(parents=True)
    paths.advice_file.write_text(
        '{"qwerty": {"rules": {"version": 3, "summary": "x", "created_at": 1,'
        ' "recommendations": ['
        '{"kind": "teleport", "keys": [97], "reason": "accuracy"},'
        '{"kind": "focus", "keys": [97], "reason": "vibes"},'
        '{"kind": "focus", "keys": [98], "reason": "accuracy", "strength": 0.5,'
        ' "evidence": [3, 40, 2], "applied": 0.3}]}}}',
        encoding="utf-8",
    )
    got = FileAdviceStore(paths).get("qwerty", "rules")
    assert got is not None
    assert [(r.kind, r.keys) for r in got.recommendations] == [(Kind.FOCUS, (98,))]
    assert got.recommendations[0].evidence == Evidence(3, 40, 2)


def test_the_evidence_keeps_its_event_sessions(paths: Paths):
    store = FileAdviceStore(paths)
    stored = advice(rec(Kind.CONTRAST, 97, 115, event_sessions=2), source="rules")
    store.put("qwerty", stored)
    got = store.get("qwerty", "rules")
    assert got is not None
    assert got.recommendations[0].evidence.event_sessions == 2
    assert got == stored


def test_evidence_of_a_bad_length_is_no_evidence(paths: Paths):
    paths.cache_dir.mkdir(parents=True)
    paths.advice_file.write_text(
        '{"qwerty": {"rules": {"version": 3, "summary": "", "created_at": 1,'
        ' "recommendations": [{"kind": "focus", "keys": [98], "reason": "accuracy",'
        ' "evidence": [3, 40]}, {"kind": "focus", "keys": [99], "reason": "accuracy",'
        ' "evidence": [3, 40, 2, 2]}]}}}',
        encoding="utf-8",
    )
    got = FileAdviceStore(paths).get("qwerty", "rules")
    assert got is not None
    assert [r.evidence for r in got.recommendations] == [Evidence(0, 0), Evidence(3, 40, 2, 2)]


@pytest.mark.parametrize("version", [1, 2])
def test_rows_of_version_1_and_2_are_ignored(paths: Paths, version: int):
    paths.cache_dir.mkdir(parents=True)
    paths.advice_file.write_text(
        f'{{"qwerty": {{"rules": {{"version": {version}, "summary": "x", "created_at": 1,'
        ' "recommendations": [{"kind": "focus", "keys": [98], "reason": "accuracy",'
        ' "evidence": [3, 40, 2], "note": "old", "applied": 0.3}]}}}',
        encoding="utf-8",
    )
    assert FileAdviceStore(paths).get("qwerty", "rules") is None


def test_a_stored_row_has_version_3_and_no_note(paths: Paths):
    FileAdviceStore(paths).put("qwerty", advice(rec(Kind.FOCUS, 97), source="rules"))
    row = json.loads(paths.advice_file.read_text(encoding="utf-8"))["qwerty"]["rules"]
    assert row["version"] == 3
    assert all("note" not in r for r in row["recommendations"])


def test_store_survives_a_corrupt_file(paths: Paths):
    paths.cache_dir.mkdir(parents=True)
    paths.advice_file.write_text("{oops", encoding="utf-8")
    assert FileAdviceStore(paths).get("qwerty", "rules") is None
    paths.advice_file.write_text('{"qwerty": []}', encoding="utf-8")
    assert FileAdviceStore(paths).get("qwerty", "rules") is None


def test_the_recency_decay_round_trips_and_defaults(paths: Paths):
    repo = TomlAdvisorConfigRepository(paths)
    assert repo.load().recency_decay == DEFAULT_RECENCY_DECAY
    repo.save(AdvisorConfig(active="rules", recency_decay=0.7))
    assert repo.load().recency_decay == 0.7
    repo.save(AdvisorConfig(active="rules", recency_decay=1.0))
    assert repo.load().recency_decay == 1.0  # equal weights


@pytest.mark.parametrize("raw", ["0", "-0.5", "1.5", '"fast"', "true"])
def test_a_bad_recency_decay_means_the_default(paths: Paths, raw: str):
    paths.config_dir.mkdir(parents=True)
    paths.advisors_file.write_text(f'active = "rules"\nrecency_decay = {raw}\n', encoding="utf-8")
    assert TomlAdvisorConfigRepository(paths).load().recency_decay == DEFAULT_RECENCY_DECAY


def test_an_integer_decay_of_one_is_accepted(paths: Paths):
    paths.config_dir.mkdir(parents=True)
    paths.advisors_file.write_text("recency_decay = 1\n", encoding="utf-8")
    assert TomlAdvisorConfigRepository(paths).load().recency_decay == 1.0
