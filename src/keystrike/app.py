"""Composition root: wire all dependencies and return a ready-to-run KeystrikeApp."""

from random import Random

from keystrike.application.build_lesson import BuildCodeLesson, BuildLesson
from keystrike.application.learn_budget_use_cases import GetDailyLearnBudget
from keystrike.application.session_use_cases import (
    FinishSession,
    RecordKeystroke,
    StartSession,
)
from keystrike.application.settings_use_cases import CycleLayout, UpdateSettings
from keystrike.application.stats_use_cases import (
    GetHeatmap,
    GetHistory,
    GetLearningRate,
    RebuildAggregates,
)
from keystrike.infrastructure.aggregates_cache import FileAggregatesCache
from keystrike.infrastructure.clock import MonotonicClock
from keystrike.infrastructure.code_generators.python import PythonCodeGenerator
from keystrike.infrastructure.freeform import FileFreeformTextProvider
from keystrike.infrastructure.id_gen import UlidGenerator
from keystrike.infrastructure.languages import BundledLanguageProvider
from keystrike.infrastructure.layout_repo import CompositeLayoutRepository
from keystrike.infrastructure.paths import default_paths, ensure_dirs
from keystrike.infrastructure.session_repo_jsonl import JsonlSessionRepository
from keystrike.infrastructure.settings_repo_toml import TomlSettingsRepository
from keystrike.presentation.textual_app import KeystrikeApp


def build() -> KeystrikeApp:
    paths = default_paths()
    ensure_dirs(paths)

    clock = MonotonicClock()
    id_gen = UlidGenerator()
    session_repo = JsonlSessionRepository(paths)
    settings_repo = TomlSettingsRepository(paths)
    layout_repo = CompositeLayoutRepository(paths)
    aggregates_cache = FileAggregatesCache(paths)
    freeform_provider = FileFreeformTextProvider()
    language_provider = BundledLanguageProvider()
    code_provider = PythonCodeGenerator()

    start = StartSession(clock=clock, id_gen=id_gen)
    record = RecordKeystroke(clock=clock, repo=session_repo)
    finish = FinishSession(clock=clock, repo=session_repo)
    rebuild_aggregates = RebuildAggregates(repo=session_repo, cache=aggregates_cache)
    get_heatmap = GetHeatmap(cache=aggregates_cache, settings_repo=settings_repo)
    get_history = GetHistory(repo=session_repo)
    get_learning_rate = GetLearningRate(repo=session_repo, settings_repo=settings_repo)
    get_daily_learn_budget = GetDailyLearnBudget(
        clock=clock,
        repo=session_repo,
        settings_repo=settings_repo,
    )
    cycle_layout = CycleLayout(settings_repo=settings_repo, layout_repo=layout_repo)
    update_settings = UpdateSettings(repo=settings_repo)
    build_lesson = BuildLesson(
        layout_repo=layout_repo,
        aggregates_cache=aggregates_cache,
        settings_repo=settings_repo,
        language_provider=language_provider,
        rng=Random(),
    )
    build_code_lesson = BuildCodeLesson(
        layout_repo=layout_repo,
        aggregates_cache=aggregates_cache,
        settings_repo=settings_repo,
        code_provider=code_provider,
        rng=Random(),
    )

    return KeystrikeApp(
        clock=clock,
        start=start,
        record=record,
        finish=finish,
        settings_repo=settings_repo,
        layout_repo=layout_repo,
        rebuild_aggregates=rebuild_aggregates,
        get_heatmap=get_heatmap,
        get_history=get_history,
        get_learning_rate=get_learning_rate,
        get_daily_learn_budget=get_daily_learn_budget,
        freeform_provider=freeform_provider,
        cycle_layout=cycle_layout,
        update_settings=update_settings,
        build_lesson=build_lesson,
        build_code_lesson=build_code_lesson,
    )
