"""PreparePracticeSession: build SessionPrep for adaptive practice."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from keystrike.application.build_lesson import BuildLesson
from keystrike.domain.enums import Mode
from keystrike.domain.models import Layout
from keystrike.domain.protocols import (
    DailyLearnBudgetProvider,
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
    get_daily_learn_budget: DailyLearnBudgetProvider

    def __call__(self) -> SessionPrep | None:
        settings = self.settings_repo.load()
        lesson = self.build_lesson(settings.layout)
        return SessionPrep(
            target_text=lesson.text,
            layout=settings.layout,
            mode=Mode.ADAPTIVE,
            focus_key=lesson.focus_key,
            focus_reason=lesson.focus_reason,
            layout_obj=self.layout_repo.get(settings.layout),
            lesson_heatmap=lesson.heatmap,
            lesson_urgency=lesson.urgency,
        )
