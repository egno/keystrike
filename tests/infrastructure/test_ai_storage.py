from __future__ import annotations

from pathlib import Path

import pytest

from keystrike.domain.ai_models import AiAnalysis, AiSettings
from keystrike.domain.models import Bigram
from keystrike.infrastructure.ai_analysis_store import FileAiAnalysisStore
from keystrike.infrastructure.ai_settings_repo_toml import TomlAiSettingsRepository
from keystrike.infrastructure.paths import Paths
from keystrike.infrastructure.sync_git import _SYNC_REL_PATHS  # pyright: ignore[reportPrivateUsage]


@pytest.fixture
def paths(tmp_path: Path) -> Paths:
    return Paths(config_dir=tmp_path / "cfg", data_dir=tmp_path / "data", log_dir=tmp_path / "log")


def test_ai_settings_round_trip_and_default(paths: Paths):
    repo = TomlAiSettingsRepository(paths)
    assert repo.load() == AiSettings()
    settings = AiSettings(provider="openai", model='m "x"', endpoint="http://h:1/v1")
    repo.save(settings)
    assert repo.load() == settings


def test_ai_settings_are_not_synced(paths: Paths):
    synced = {paths.config_dir / rel for rel in _SYNC_REL_PATHS}
    assert paths.ai_settings_file not in synced
    assert paths.ai_settings_file.parent == paths.config_dir


def test_legacy_keys_in_settings_toml_are_read_once(paths: Paths):
    paths.config_dir.mkdir(parents=True)
    paths.settings_file.write_text(
        'ai_provider = "ollama"\nai_model = "qwen"\nai_endpoint = "http://box:11434"\n',
        encoding="utf-8",
    )
    repo = TomlAiSettingsRepository(paths)
    assert repo.load() == AiSettings(provider="ollama", model="qwen", endpoint="http://box:11434")
    repo.save(AiSettings())
    assert repo.load() == AiSettings()  # ai.toml wins from now on


def test_unknown_provider_or_bad_file_falls_back_to_off(paths: Paths):
    paths.config_dir.mkdir(parents=True)
    paths.ai_settings_file.write_text('provider = "mystery"\n', encoding="utf-8")
    assert TomlAiSettingsRepository(paths).load().provider == ""
    paths.ai_settings_file.write_text("not = [toml", encoding="utf-8")
    assert TomlAiSettingsRepository(paths).load() == AiSettings()


def test_analysis_store_round_trip_per_layout(paths: Paths):
    store = FileAiAnalysisStore(paths)
    assert store.get("qwerty") is None
    qwerty = AiAnalysis(
        layout="qwerty",
        summary="Slow on s",
        focus_key=115,
        focus_pair=Bigram(97, 115),
        rest_keys=(97,),
        emphasis_keys=(115, 100),
        created_at=12.5,
    )
    colemak = AiAnalysis(layout="colemak", focus_key=101)
    store.put(qwerty)
    store.put(colemak)
    assert FileAiAnalysisStore(paths).get("qwerty") == qwerty
    assert FileAiAnalysisStore(paths).get("colemak") == colemak


def test_analysis_store_ignores_failures_and_clears(paths: Paths):
    store = FileAiAnalysisStore(paths)
    store.put(AiAnalysis(layout="qwerty", error="boom"))
    assert store.get("qwerty") is None
    store.put(AiAnalysis(layout="qwerty", focus_key=97))
    store.clear()
    assert store.get("qwerty") is None


def test_analysis_store_survives_a_corrupt_file(paths: Paths):
    paths.cache_dir.mkdir(parents=True)
    paths.ai_analysis_file.write_text("{oops", encoding="utf-8")
    assert FileAiAnalysisStore(paths).get("qwerty") is None
