"""PreparePracticeSession: build SessionPrep for each PracticeSource choice."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from keystrike.application.build_lesson import BuildCodeLesson, BuildLesson
from keystrike.domain.enums import Mode, PracticeSource
from keystrike.domain.models import Layout
from keystrike.domain.protocols import (
    DailyLearnBudgetProvider,
    FreeformTextProvider,
    LayoutRepository,
    SettingsRepository,
)

PrepareNextSession = Callable[[], "SessionPrep | None"]


@dataclass(frozen=True, slots=True)
class SessionPrep:
    target_text: str
    layout: str
    mode: Mode
    focus_key: int | None
    focus_reason: str | None
    layout_obj: Layout | None
    lesson_heatmap: dict[int, float] | None
    lesson_urgency: dict[int, float] | None


@dataclass(slots=True)
class PreparePracticeSession:
    settings_repo: SettingsRepository
    layout_repo: LayoutRepository
    build_lesson: BuildLesson
    build_code_lesson: BuildCodeLesson
    freeform_provider: FreeformTextProvider
    get_daily_learn_budget: DailyLearnBudgetProvider
    sample_text: str

    def __call__(self, source: PracticeSource) -> SessionPrep | None:
        settings = self.settings_repo.load()
        mode = Mode.FREE
        focus_key: int | None = None
        focus_reason: str | None = None
        layout_obj: Layout | None = None
        lesson_heatmap: dict[int, float] | None = None
        lesson_urgency: dict[int, float] | None = None
        target_text = self.sample_text

        if source is PracticeSource.ADAPTIVE:
            if self.get_daily_learn_budget().limit_reached:
                return None
            lesson = self.build_lesson(settings.layout)
            target_text = lesson.text
            mode = Mode.ADAPTIVE
            focus_key = lesson.focus_key
            focus_reason = lesson.focus_reason
            layout_obj = self.layout_repo.get(settings.layout)
            lesson_heatmap = lesson.heatmap
            lesson_urgency = lesson.urgency
        elif source is PracticeSource.CODE:
            lesson = self.build_code_lesson(settings.layout)
            target_text = lesson.text
            mode = Mode.CODE
            focus_key = lesson.focus_key
            focus_reason = lesson.focus_reason
            layout_obj = self.layout_repo.get(settings.layout)
            lesson_heatmap = lesson.heatmap
            lesson_urgency = lesson.urgency
        elif source is PracticeSource.FREE and settings.freeform_path:
            target_text = self.freeform_provider.load(Path(settings.freeform_path))
        elif source is PracticeSource.SAMPLE:
            target_text = self.sample_text

        return SessionPrep(
            target_text=target_text,
            layout=settings.layout,
            mode=mode,
            focus_key=focus_key,
            focus_reason=focus_reason,
            layout_obj=layout_obj,
            lesson_heatmap=lesson_heatmap,
            lesson_urgency=lesson_urgency,
        )
