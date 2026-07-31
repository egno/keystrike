"""Composition root: wire all dependencies and return a ready-to-run KeystrikeApp."""

from dataclasses import dataclass
from random import Random

from keystrike.application.build_lesson import BuildLesson
from keystrike.application.learn_budget_use_cases import GetDailyLearnBudget
from keystrike.application.prepare_practice import PreparePracticeSession
from keystrike.application.session_use_cases import (
    AbortSession,
    FinishSession,
    GetSessionBaseline,
    RecordKeystroke,
    StartSession,
)
from keystrike.application.settings_use_cases import CycleLayout, UpdateSettings
from keystrike.application.stats_use_cases import (
    GetAggregateMetricTrends,
    GetHeatmap,
    GetHistory,
    GetKeyMetricTrends,
    GetOrRebuildAggregates,
    RebuildAggregates,
)
from keystrike.application.sync_use_cases import GetSyncStatus, InitSync, PullSync, PushSync
from keystrike.application.wordlist_use_cases import (
    ClearWordList,
    GetWordListCacheStatus,
    ImportWordList,
)
from keystrike.domain.version import __version__
from keystrike.infrastructure.aggregates_cache import FileAggregatesCache
from keystrike.infrastructure.clock import MonotonicClock
from keystrike.infrastructure.id_gen import UlidGenerator
from keystrike.infrastructure.languages import BundledLanguageProvider
from keystrike.infrastructure.layout_repo import CompositeLayoutRepository
from keystrike.infrastructure.paths import default_paths, ensure_dirs
from keystrike.infrastructure.session_repo_jsonl import JsonlSessionRepository
from keystrike.infrastructure.settings_repo_toml import TomlSettingsRepository
from keystrike.infrastructure.sync_git import GitSyncGateway
from keystrike.infrastructure.wordlist_store import FileWordListStore
from keystrike.presentation.services import (
    HomeServices,
    PracticeServices,
    SettingsServices,
    StatsServices,
)
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
    rebuild = RebuildAggregates(
        repo=session_repo,
        cache=aggregates_cache,
        settings_repo=TomlSettingsRepository(paths),
    )
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
    record = RecordKeystroke(clock=clock)
    finish = FinishSession(
        clock=clock,
        repo=session_repo,
        settings_repo=settings_repo,
        layout_repo=layout_repo,
    )
    abort = AbortSession()
    get_session_baseline = GetSessionBaseline(repo=session_repo, settings_repo=settings_repo)
    rebuild_aggregates = RebuildAggregates(
        repo=session_repo,
        cache=aggregates_cache,
        settings_repo=settings_repo,
    )
    ensure_aggregates = GetOrRebuildAggregates(
        repo=session_repo,
        cache=aggregates_cache,
        rebuild=rebuild_aggregates,
    )
    get_heatmap = GetHeatmap(cache=aggregates_cache, settings_repo=settings_repo, clock=clock)
    get_history = GetHistory(repo=session_repo)
    get_key_metric_trends = GetKeyMetricTrends(
        repo=session_repo,
        settings_repo=settings_repo,
    )
    get_aggregate_metric_trends = GetAggregateMetricTrends(
        repo=session_repo,
        settings_repo=settings_repo,
    )
    get_daily_learn_budget = GetDailyLearnBudget(
        clock=clock,
        repo=session_repo,
        settings_repo=settings_repo,
    )
    cycle_layout = CycleLayout(settings_repo=settings_repo, layout_repo=layout_repo)
    update_settings = UpdateSettings(repo=settings_repo)
    wordlist_store = FileWordListStore(paths)
    # Shared by BuildLesson (load), ImportWordList (download), GetWordListCacheStatus.
    import_wordlist = ImportWordList(store=wordlist_store, settings_repo=settings_repo)
    clear_wordlist = ClearWordList(settings_repo=settings_repo)
    get_wordlist_cache_status = GetWordListCacheStatus(store=wordlist_store)
    build_lesson = BuildLesson(
        layout_repo=layout_repo,
        aggregates_cache=aggregates_cache,
        settings_repo=settings_repo,
        language_provider=language_provider,
        wordlist_store=wordlist_store,
        rng=Random(),
        clock=clock,
    )
    prepare_practice = PreparePracticeSession(
        settings_repo=settings_repo,
        layout_repo=layout_repo,
        build_lesson=build_lesson,
        get_daily_learn_budget=get_daily_learn_budget,
        ensure_aggregates=ensure_aggregates,
    )

    return KeystrikeApp(
        home=HomeServices(
            settings_repo=settings_repo,
            cycle_layout=cycle_layout,
            get_daily_learn_budget=get_daily_learn_budget,
        ),
        practice=PracticeServices(
            clock=clock,
            start=start,
            record=record,
            finish=finish,
            abort=abort,
            prepare_practice=prepare_practice,
            get_session_baseline=get_session_baseline,
            rebuild_aggregates=rebuild_aggregates,
            get_daily_learn_budget=get_daily_learn_budget,
        ),
        stats=StatsServices(
            layout_repo=layout_repo,
            rebuild_aggregates=rebuild_aggregates,
            get_heatmap=get_heatmap,
            get_history=get_history,
            get_key_metric_trends=get_key_metric_trends,
            get_aggregate_metric_trends=get_aggregate_metric_trends,
        ),
        settings=SettingsServices(
            settings_repo=settings_repo,
            layout_repo=layout_repo,
            update_settings=update_settings,
            import_wordlist=import_wordlist,
            clear_wordlist=clear_wordlist,
            get_wordlist_cache_status=get_wordlist_cache_status,
        ),
        app_version=__version__,
    )
