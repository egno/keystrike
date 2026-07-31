"""PreparePracticeSession: build SessionPrep for adaptive practice."""

from __future__ import annotations

from dataclasses import dataclass

from keystrike.application.build_lesson import BuildLesson
from keystrike.domain.enums import Mode
from keystrike.domain.focus import FocusReason
from keystrike.domain.models import Layout
from keystrike.domain.null_adapters import NULL_AGGREGATES_ENSURER
from keystrike.domain.protocols import (
    AggregatesEnsurer,
    DailyLearnBudgetProvider,
    LayoutRepository,
    SettingsRepository,
)


@dataclass(frozen=True, slots=True)
class SessionPrep:
    target_text: str
    layout: str
    mode: Mode
    focus_key: int | None
    focus_reason: FocusReason | None
    focus_confidence: float | None
    focus_speed: float | None
    focus_accuracy: float | None
    focus_attempts: int | None
    focus_min_attempts: int | None
    layout_obj: Layout | None
    lesson_heatmap: dict[int, float] | None
    lesson_urgency: dict[int, float] | None


@dataclass(slots=True)
class PreparePracticeSession:
    settings_repo: SettingsRepository
    layout_repo: LayoutRepository
    build_lesson: BuildLesson
    get_daily_learn_budget: DailyLearnBudgetProvider
    ensure_aggregates: AggregatesEnsurer = NULL_AGGREGATES_ENSURER

    def __call__(self) -> SessionPrep | None:
        settings = self.settings_repo.load()
        self.ensure_aggregates(settings.layout)
        lesson = self.build_lesson(settings.layout)
        return SessionPrep(
            target_text=lesson.text,
            layout=settings.layout,
            mode=Mode.ADAPTIVE,
            focus_key=lesson.focus_key,
            focus_reason=lesson.focus_reason,
            focus_confidence=lesson.focus_confidence,
            focus_speed=lesson.focus_speed,
            focus_accuracy=lesson.focus_accuracy,
            focus_attempts=lesson.focus_attempts,
            focus_min_attempts=lesson.focus_min_attempts,
            layout_obj=self.layout_repo.get(settings.layout),
            lesson_heatmap=lesson.skill_heatmap,
            lesson_urgency=lesson.urgency,
        )
