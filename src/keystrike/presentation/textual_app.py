from typing import ClassVar

from textual.app import App
from textual.binding import BindingType

from keystrike.application.prepare_practice import PreparePracticeSession
from keystrike.application.session_use_cases import (
    FinishSession,
    RecordKeystroke,
    StartSession,
)
from keystrike.application.settings_use_cases import CycleLayout, UpdateSettings
from keystrike.application.stats_use_cases import GetHeatmap, GetHistory
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


class KeystrikeApp(App[None]):
    ENABLE_COMMAND_PALETTE = False
    BINDINGS: ClassVar[list[BindingType]] = [QUIT]

    def __init__(
        self,
        *,
        clock: Clock,
        start: StartSession,
        record: RecordKeystroke,
        finish: FinishSession,
        settings_repo: SettingsRepository,
        layout_repo: LayoutRepository,
        prepare_practice: PreparePracticeSession,
        rebuild_aggregates: StatsRebuilder,
        get_heatmap: GetHeatmap,
        get_history: GetHistory,
        cycle_layout: CycleLayout,
        update_settings: UpdateSettings,
        import_wordlist: ImportWordList,
        clear_wordlist: ClearWordList,
        get_wordlist_cache_status: GetWordListCacheStatus,
        get_daily_learn_budget: DailyLearnBudgetProvider = NULL_DAILY_LEARN_BUDGET,
        app_version: str = "",
    ) -> None:
        super().__init__()
        self._clock = clock
        self._start = start
        self._record = record
        self._finish = finish
        self._settings_repo = settings_repo
        self._layout_repo = layout_repo
        self._prepare_practice = prepare_practice
        self._rebuild_aggregates = rebuild_aggregates
        self._get_heatmap = get_heatmap
        self._get_history = get_history
        self._cycle_layout = cycle_layout
        self._update_settings = update_settings
        self._import_wordlist = import_wordlist
        self._clear_wordlist = clear_wordlist
        self._get_wordlist_cache_status = get_wordlist_cache_status
        self._get_daily_learn_budget = get_daily_learn_budget
        self._app_version = app_version

    def on_mount(self) -> None:
        self.install_screen(self._build_home(), name="home")
        self.push_screen("home")

    def _build_home(self) -> HomeScreen:
        return HomeScreen(
            settings_repo=self._settings_repo,
            cycle_layout=self._cycle_layout,
            get_daily_learn_budget=self._get_daily_learn_budget,
            app_version=self._app_version,
        )

    def on_home_screen_start_practice(self, _: HomeScreen.StartPractice) -> None:
        initial = self._prepare_practice()
        if initial is None:
            return

        practice = PracticeScreen(
            start=self._start,
            record=self._record,
            finish=self._finish,
            clock=self._clock,
            initial=initial,
            prepare_next=self._prepare_practice,
            rebuild_aggregates=self._rebuild_aggregates,
            get_daily_learn_budget=self._get_daily_learn_budget,
        )
        self.push_screen(practice)

    def on_home_screen_open_stats(self, _: HomeScreen.OpenStats) -> None:
        settings = self._settings_repo.load()
        self.push_screen(
            StatsScreen(
                layout=settings.layout,
                layout_repo=self._layout_repo,
                rebuild_aggregates=self._rebuild_aggregates,
                get_heatmap=self._get_heatmap,
                get_history=self._get_history,
                current_target_speed_cpm=settings.target_speed_cpm,
            )
        )

    def on_home_screen_open_settings(self, _: HomeScreen.OpenSettings) -> None:
        self.push_screen(
            SettingsScreen(
                settings_repo=self._settings_repo,
                layout_repo=self._layout_repo,
                update_settings=self._update_settings,
                import_wordlist=self._import_wordlist,
                clear_wordlist=self._clear_wordlist,
                get_wordlist_cache_status=self._get_wordlist_cache_status,
            )
        )

    def action_quit_app(self) -> None:
        self.exit()
