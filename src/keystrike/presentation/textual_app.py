from pathlib import Path

from textual.app import App

from keystrike.application.build_lesson import BuildCodeLesson, BuildLesson
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
from keystrike.domain.enums import Mode, PracticeSource
from keystrike.domain.null_adapters import NULL_DAILY_LEARN_BUDGET
from keystrike.domain.protocols import (
    Clock,
    DailyLearnBudgetProvider,
    FreeformTextProvider,
    LayoutRepository,
    SettingsRepository,
)
from keystrike.presentation.screens.home import HomeScreen
from keystrike.presentation.screens.practice import PracticeScreen
from keystrike.presentation.screens.settings import SettingsScreen
from keystrike.presentation.screens.stats import StatsScreen

# M1 sample text — a short paragraph, always available regardless of freeform_path.
_SAMPLE_TEXT = (
    "the quick brown fox jumps over the lazy dog. "
    "pack my box with five dozen liquor jugs. "
    "how vexingly quick daft zebras jump."
)


class KeystrikeApp(App[None]):
    ENABLE_COMMAND_PALETTE = False

    def __init__(
        self,
        *,
        clock: Clock,
        start: StartSession,
        record: RecordKeystroke,
        finish: FinishSession,
        settings_repo: SettingsRepository,
        layout_repo: LayoutRepository,
        rebuild_aggregates: RebuildAggregates,
        get_heatmap: GetHeatmap,
        get_history: GetHistory,
        get_learning_rate: GetLearningRate,
        freeform_provider: FreeformTextProvider,
        cycle_layout: CycleLayout,
        update_settings: UpdateSettings,
        build_lesson: BuildLesson,
        build_code_lesson: BuildCodeLesson,
        get_daily_learn_budget: DailyLearnBudgetProvider = NULL_DAILY_LEARN_BUDGET,
        sample_text: str = _SAMPLE_TEXT,
    ) -> None:
        super().__init__()
        self._clock = clock
        self._start = start
        self._record = record
        self._finish = finish
        self._settings_repo = settings_repo
        self._layout_repo = layout_repo
        self._rebuild_aggregates = rebuild_aggregates
        self._get_heatmap = get_heatmap
        self._get_history = get_history
        self._get_learning_rate = get_learning_rate
        self._freeform_provider = freeform_provider
        self._cycle_layout = cycle_layout
        self._update_settings = update_settings
        self._build_lesson = build_lesson
        self._build_code_lesson = build_code_lesson
        self._get_daily_learn_budget = get_daily_learn_budget
        self._sample_text = sample_text

    def on_mount(self) -> None:
        self.install_screen(self._build_home(), name="home")
        self.push_screen("home")

    def _build_home(self) -> HomeScreen:
        return HomeScreen(
            settings_repo=self._settings_repo,
            cycle_layout=self._cycle_layout,
            get_daily_learn_budget=self._get_daily_learn_budget,
        )

    def on_home_screen_start_practice(self, message: HomeScreen.StartPractice) -> None:
        settings = self._settings_repo.load()
        mode = Mode.FREE
        focus_key: int | None = None
        layout_obj = None
        lesson_heatmap = None

        if message.source is PracticeSource.ADAPTIVE:
            if self._get_daily_learn_budget().limit_reached:
                self.notify(
                    "Daily learn limit reached. Change learn_daily_minutes in Settings "
                    "or try sample/code/free practice.",
                    severity="warning",
                )
                return
            lesson = self._build_lesson(settings.layout)
            target_text = lesson.text
            mode = Mode.ADAPTIVE
            focus_key = lesson.focus_key
            layout_obj = self._layout_repo.get(settings.layout)
            lesson_heatmap = lesson.heatmap
        elif message.source is PracticeSource.CODE:
            lesson = self._build_code_lesson(settings.layout)
            target_text = lesson.text
            mode = Mode.CODE
            focus_key = lesson.focus_key
            layout_obj = self._layout_repo.get(settings.layout)
            lesson_heatmap = lesson.heatmap
        elif message.source is PracticeSource.FREE and settings.freeform_path:
            target_text = self._freeform_provider.load(Path(settings.freeform_path))
        else:
            target_text = self._sample_text

        practice = PracticeScreen(
            start=self._start,
            record=self._record,
            finish=self._finish,
            clock=self._clock,
            target_text=target_text,
            layout=settings.layout,
            mode=mode,
            focus_key=focus_key,
            rebuild_aggregates=self._rebuild_aggregates,
            get_learning_rate=self._get_learning_rate,
            get_daily_learn_budget=self._get_daily_learn_budget,
            layout_obj=layout_obj,
            lesson_heatmap=lesson_heatmap,
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
            )
        )

    def on_home_screen_open_settings(self, _: HomeScreen.OpenSettings) -> None:
        self.push_screen(
            SettingsScreen(
                settings_repo=self._settings_repo,
                layout_repo=self._layout_repo,
                update_settings=self._update_settings,
            )
        )
