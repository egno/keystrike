"""Composition root: wire all dependencies and return a ready-to-run KeystrikeApp."""

from dataclasses import dataclass
from random import Random

from keystrike.application.build_lesson import BuildLesson
from keystrike.application.learn_budget_use_cases import GetDailyLearnBudget
from keystrike.application.prepare_practice import PreparePracticeSession
from keystrike.application.session_use_cases import (
    FinishSession,
    RecordKeystroke,
    StartSession,
)
from keystrike.application.settings_use_cases import CycleLayout, UpdateSettings
from keystrike.application.stats_use_cases import GetHeatmap, GetHistory, RebuildAggregates
from keystrike.application.sync_use_cases import GetSyncStatus, InitSync, PullSync, PushSync
from keystrike.infrastructure.aggregates_cache import FileAggregatesCache
from keystrike.infrastructure.clock import MonotonicClock
from keystrike.infrastructure.id_gen import UlidGenerator
from keystrike.infrastructure.languages import BundledLanguageProvider
from keystrike.infrastructure.layout_repo import CompositeLayoutRepository
from keystrike.infrastructure.paths import default_paths, ensure_dirs
from keystrike.infrastructure.session_repo_jsonl import JsonlSessionRepository
from keystrike.infrastructure.settings_repo_toml import TomlSettingsRepository
from keystrike.infrastructure.sync_git import GitSyncGateway
from keystrike.presentation.textual_app import KeystrikeApp


@dataclass(frozen=True, slots=True)
class SyncServices:
    init: InitSync
    pull: PullSync
    push: PushSync
    status: GetSyncStatus


def build_sync() -> SyncServices:
    paths = default_paths()
    ensure_dirs(paths)
    session_repo = JsonlSessionRepository(paths)
    aggregates_cache = FileAggregatesCache(paths)
    store = GitSyncGateway(paths)
    rebuild = RebuildAggregates(repo=session_repo, cache=aggregates_cache)
    return SyncServices(
        init=InitSync(gateway=store),
        pull=PullSync(gateway=store, rebuild=rebuild),
        push=PushSync(gateway=store),
        status=GetSyncStatus(gateway=store),
    )


def build() -> KeystrikeApp:
    paths = default_paths()
    ensure_dirs(paths)

    clock = MonotonicClock()
    id_gen = UlidGenerator()
    session_repo = JsonlSessionRepository(paths)
    settings_repo = TomlSettingsRepository(paths)
    layout_repo = CompositeLayoutRepository(paths)
    aggregates_cache = FileAggregatesCache(paths)
    language_provider = BundledLanguageProvider()

    start = StartSession(clock=clock, id_gen=id_gen)
    record = RecordKeystroke(clock=clock, repo=session_repo)
    finish = FinishSession(
        clock=clock,
        repo=session_repo,
        aggregates_cache=aggregates_cache,
        settings_repo=settings_repo,
        layout_repo=layout_repo,
    )
    rebuild_aggregates = RebuildAggregates(repo=session_repo, cache=aggregates_cache)
    get_heatmap = GetHeatmap(cache=aggregates_cache, settings_repo=settings_repo)
    get_history = GetHistory(repo=session_repo)
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
    prepare_practice = PreparePracticeSession(
        settings_repo=settings_repo,
        layout_repo=layout_repo,
        build_lesson=build_lesson,
        get_daily_learn_budget=get_daily_learn_budget,
    )

    return KeystrikeApp(
        clock=clock,
        start=start,
        record=record,
        finish=finish,
        settings_repo=settings_repo,
        layout_repo=layout_repo,
        prepare_practice=prepare_practice,
        rebuild_aggregates=rebuild_aggregates,
        get_heatmap=get_heatmap,
        get_history=get_history,
        cycle_layout=cycle_layout,
        update_settings=update_settings,
        get_daily_learn_budget=get_daily_learn_budget,
    )
