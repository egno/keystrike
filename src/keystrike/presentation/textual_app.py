from dataclasses import dataclass
from typing import ClassVar

from textual.app import App
from textual.binding import BindingType

from keystrike.application.prepare_practice import PreparePracticeSession
from keystrike.application.session_use_cases import (
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
from keystrike.presentation.bindings import QUIT
from keystrike.presentation.screens.home import HomeScreen
from keystrike.presentation.screens.practice import PracticeScreen
from keystrike.presentation.screens.settings import SettingsScreen
from keystrike.presentation.screens.stats import StatsScreen


@dataclass(frozen=True, slots=True)
class HomeServices:
    cycle_layout: CycleLayout
    get_daily_learn_budget: DailyLearnBudgetProvider = NULL_DAILY_LEARN_BUDGET


@dataclass(frozen=True, slots=True)
class PracticeServices:
    clock: Clock
    start: StartSession
    record: RecordKeystroke
    finish: FinishSession
    prepare_practice: PreparePracticeSession
    get_session_baseline: GetSessionBaseline
    rebuild_aggregates: StatsRebuilder
    get_daily_learn_budget: DailyLearnBudgetProvider = NULL_DAILY_LEARN_BUDGET


@dataclass(frozen=True, slots=True)
class StatsServices:
    rebuild_aggregates: StatsRebuilder
    get_heatmap: GetHeatmap
    get_history: GetHistory
    get_key_metric_trends: GetKeyMetricTrends
    get_aggregate_metric_trends: GetAggregateMetricTrends


@dataclass(frozen=True, slots=True)
class SettingsServices:
    update_settings: UpdateSettings
    import_wordlist: ImportWordList
    clear_wordlist: ClearWordList
    get_wordlist_cache_status: GetWordListCacheStatus


class KeystrikeApp(App[None]):
    ENABLE_COMMAND_PALETTE = False
    BINDINGS: ClassVar[list[BindingType]] = [QUIT]

    def __init__(
        self,
        *,
        settings_repo: SettingsRepository,
        layout_repo: LayoutRepository,
        home: HomeServices,
        practice: PracticeServices,
        stats: StatsServices,
        settings: SettingsServices,
        app_version: str = "",
    ) -> None:
        super().__init__()
        self._settings_repo = settings_repo
        self._layout_repo = layout_repo
        self._home = home
        self._practice = practice
        self._stats = stats
        self._settings = settings
        self._app_version = app_version

    def on_mount(self) -> None:
        self.install_screen(self._build_home(), name="home")
        self.push_screen("home")

    def _build_home(self) -> HomeScreen:
        return HomeScreen(
            settings_repo=self._settings_repo,
            cycle_layout=self._home.cycle_layout,
            get_daily_learn_budget=self._home.get_daily_learn_budget,
            app_version=self._app_version,
        )

    def on_home_screen_start_practice(self, _: HomeScreen.StartPractice) -> None:
        initial = self._practice.prepare_practice()
        if initial is None:
            return

        practice = PracticeScreen(
            start=self._practice.start,
            record=self._practice.record,
            finish=self._practice.finish,
            clock=self._practice.clock,
            initial=initial,
            prepare_next=self._practice.prepare_practice,
            get_session_baseline=self._practice.get_session_baseline,
            rebuild_aggregates=self._practice.rebuild_aggregates,
            get_daily_learn_budget=self._practice.get_daily_learn_budget,
        )
        self.push_screen(practice)

    def on_home_screen_open_stats(self, _: HomeScreen.OpenStats) -> None:
        settings = self._settings_repo.load()
        self.push_screen(
            StatsScreen(
                layout=settings.layout,
                layout_repo=self._layout_repo,
                rebuild_aggregates=self._stats.rebuild_aggregates,
                get_heatmap=self._stats.get_heatmap,
                get_history=self._stats.get_history,
                get_key_metric_trends=self._stats.get_key_metric_trends,
                get_aggregate_metric_trends=self._stats.get_aggregate_metric_trends,
                current_target_speed_cpm=settings.target_speed_cpm,
                confidence_session_window=settings.confidence_session_window,
            )
        )

    def on_home_screen_open_settings(self, _: HomeScreen.OpenSettings) -> None:
        self.push_screen(
            SettingsScreen(
                settings_repo=self._settings_repo,
                layout_repo=self._layout_repo,
                update_settings=self._settings.update_settings,
                import_wordlist=self._settings.import_wordlist,
                clear_wordlist=self._settings.clear_wordlist,
                get_wordlist_cache_status=self._settings.get_wordlist_cache_status,
            )
        )

    def action_quit_app(self) -> None:
        self.exit()
