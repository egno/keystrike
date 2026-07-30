"""Per-screen dependency-injection bundles, shared by the composition root (app.py),
KeystrikeApp, and the screens themselves. Split out from textual_app.py so screens can
depend on these types without importing textual_app.py (which imports the screens).
"""

from dataclasses import dataclass

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
)
from keystrike.application.wordlist_use_cases import (
    ClearWordList,
    GetWordListCacheStatus,
    ImportWordList,
)
from keystrike.domain.null_adapters import NULL_DAILY_LEARN_BUDGET
from keystrike.domain.protocols import (
    Clock,
    DailyLearnBudgetProvider,
    LayoutRepository,
    SettingsRepository,
    StatsRebuilder,
)


@dataclass(frozen=True, slots=True)
class HomeServices:
    settings_repo: SettingsRepository
    cycle_layout: CycleLayout
    get_daily_learn_budget: DailyLearnBudgetProvider = NULL_DAILY_LEARN_BUDGET


@dataclass(frozen=True, slots=True)
class PracticeServices:
    clock: Clock
    start: StartSession
    record: RecordKeystroke
    finish: FinishSession
    abort: AbortSession
    prepare_practice: PreparePracticeSession
    get_session_baseline: GetSessionBaseline
    rebuild_aggregates: StatsRebuilder
    get_daily_learn_budget: DailyLearnBudgetProvider = NULL_DAILY_LEARN_BUDGET


@dataclass(frozen=True, slots=True)
class StatsServices:
    layout_repo: LayoutRepository
    rebuild_aggregates: StatsRebuilder
    get_heatmap: GetHeatmap
    get_history: GetHistory
    get_key_metric_trends: GetKeyMetricTrends
    get_aggregate_metric_trends: GetAggregateMetricTrends


@dataclass(frozen=True, slots=True)
class SettingsServices:
    settings_repo: SettingsRepository
    layout_repo: LayoutRepository
    update_settings: UpdateSettings
    import_wordlist: ImportWordList
    clear_wordlist: ClearWordList
    get_wordlist_cache_status: GetWordListCacheStatus
