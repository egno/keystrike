"""BuildLesson / BuildCodeLesson: the adaptive engine — figure out which keys
are unlocked, pick a focus key, and generate practice text for them.

Both share the same unlock/focus/state logic (`_lesson_progress`); they only
differ in how they turn "unlocked keys + focus key" into practice text —
Markov-generated words for English (M3), real code snippets biased toward
the focus key for code mode (M4, since code syntax can't be filtered to a
hard alphabet the way English words can).
"""

from __future__ import annotations

from dataclasses import dataclass
from random import Random

from keystrike.domain.code_lesson import select_snippet
from keystrike.domain.confidence import (
    compute_unlocked,
    confidence_of,
    select_focus,
    target_ms_per_char,
)
from keystrike.domain.generator import AdaptiveGenerator
from keystrike.domain.models import KeyStats, Layout, LessonKey, LessonState, Settings
from keystrike.domain.protocols import (
    AggregatesCache,
    CodeSnippetProvider,
    LanguageProvider,
    LayoutRepository,
    SettingsRepository,
)

WORD_COUNT = 12


@dataclass(slots=True)
class Lesson:
    text: str
    state: LessonState

    @property
    def focus_key(self) -> int:
        return next(k.codepoint for k in self.state.keys if k.is_focus)


def _lesson_progress(
    layout_name: str, layout: Layout, stats: dict[int, KeyStats], settings: Settings,
) -> tuple[tuple[int, ...], int, LessonState]:
    target = target_ms_per_char(settings.target_speed_cpm)
    unlocked = compute_unlocked(
        layout.learn_order,
        settings.alphabet_size,
        stats,
        target,
        recover_keys=settings.recover_keys,
    )
    focus = select_focus(unlocked, stats, target, settings.recover_keys)

    keys = tuple(
        LessonKey(
            codepoint=cp,
            unlocked=True,
            confidence=confidence_of(cp, stats, target, settings.recover_keys),
            is_focus=(cp == focus),
        )
        for cp in unlocked
    )
    state = LessonState(
        layout=layout_name,
        keys=keys,
        alphabet_size=settings.alphabet_size,
        target_speed_cpm=settings.target_speed_cpm,
        recover_keys=settings.recover_keys,
    )
    return unlocked, focus, state


@dataclass(slots=True)
class BuildLesson:
    layout_repo: LayoutRepository
    aggregates_cache: AggregatesCache
    settings_repo: SettingsRepository
    language_provider: LanguageProvider
    rng: Random

    def __call__(self, layout_name: str) -> Lesson:
        settings = self.settings_repo.load()
        layout = self.layout_repo.get(layout_name)
        stats = self.aggregates_cache.get(layout_name) or {}
        unlocked, focus, state = _lesson_progress(layout_name, layout, stats, settings)

        table = self.language_provider.transitions(settings.lang)
        generator = AdaptiveGenerator(table=table, rng=self.rng)
        alphabet_chars = frozenset(chr(cp) for cp in unlocked)
        text = generator.generate_lesson(alphabet_chars, chr(focus), word_count=WORD_COUNT)

        return Lesson(text=text, state=state)


@dataclass(slots=True)
class BuildCodeLesson:
    layout_repo: LayoutRepository
    aggregates_cache: AggregatesCache
    settings_repo: SettingsRepository
    code_provider: CodeSnippetProvider
    rng: Random

    def __call__(self, layout_name: str) -> Lesson:
        settings = self.settings_repo.load()
        layout = self.layout_repo.get(layout_name)
        stats = self.aggregates_cache.get(layout_name) or {}
        _unlocked, focus, state = _lesson_progress(layout_name, layout, stats, settings)

        text = select_snippet(self.code_provider.snippets(), chr(focus), self.rng)

        return Lesson(text=text, state=state)
