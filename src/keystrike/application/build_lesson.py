"""BuildLesson: the adaptive engine — figure out which keys are unlocked,
pick a focus key, and generate practice text for them.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from random import Random

from keystrike.domain.aggregate import transition_key
from keystrike.domain.confidence import (
    accuracy_of,
    compute_unlocked,
    confidence_of,
    focus_key_from_transition,
    key_confidence,
    practice_weight,
    review_urgency,
    round_confidence,
    select_focus,
    select_focus_transition,
    target_ms_per_char,
    transition_accuracy_of,
    transition_confidence,
    transition_confidence_of,
    transition_practice_weight,
)
from keystrike.domain.generator import AdaptiveGenerator
from keystrike.domain.learn_order import keyboard_order
from keystrike.domain.models import (
    KeyStats,
    Layout,
    LessonKey,
    LessonState,
    Settings,
    TransitionStats,
)
from keystrike.domain.protocols import (
    AggregatesCache,
    LanguageProvider,
    LayoutRepository,
    SettingsRepository,
    WordListStore,
)
from keystrike.domain.wordlist import words_for_alphabet

WORD_COUNT = 12
_CONFIDENCE_GOOD = 1.0


def _key_focus_metrics(
    focus: int,
    stats: dict[int, KeyStats],
    target: float,
) -> tuple[float, float]:
    key_stats = stats.get(focus)
    if key_stats is None:
        return 0.0, 0.0
    return (
        round_confidence(key_confidence(target, key_stats.mean_time_ns)),
        round_confidence(accuracy_of(key_stats)),
    )


def _transition_focus_metrics(
    prev_cp: int,
    next_cp: int,
    transitions: dict[str, TransitionStats],
    target: float,
) -> tuple[float, float]:
    t_stats = transitions.get(transition_key(prev_cp, next_cp))
    if t_stats is None:
        return 0.0, 0.0
    return (
        round_confidence(transition_confidence(target, t_stats.mean_time_ns)),
        round_confidence(transition_accuracy_of(t_stats)),
    )


def _focus_reason(
    focus: int,
    stats: dict[int, KeyStats],
    target: float,
    now: float,
    *,
    min_attempts: int,
) -> str | None:
    key_stats = stats.get(focus)
    urgency = review_urgency(key_stats.last_seen if key_stats else 0.0, now)
    confidence = confidence_of(focus, stats, target, min_attempts=min_attempts)
    if urgency > 0 and confidence >= _CONFIDENCE_GOOD:
        return "review"
    if confidence < _CONFIDENCE_GOOD:
        return "weak"
    return None


def _focus_reason_transition(
    prev_cp: int,
    next_cp: int,
    transitions: dict[str, TransitionStats],
    target: float,
    now: float,
    *,
    min_attempts: int,
) -> str | None:
    pair = chr(prev_cp) + chr(next_cp)
    t_stats = transitions.get(transition_key(prev_cp, next_cp))
    urgency = review_urgency(t_stats.last_seen if t_stats else 0.0, now)
    confidence = transition_confidence_of(
        prev_cp, next_cp, transitions, target, min_attempts=min_attempts,
    )
    if urgency > 0 and confidence >= _CONFIDENCE_GOOD:
        return f"{pair} review transition"
    if confidence < _CONFIDENCE_GOOD:
        return f"{pair} weak transition"
    return None


@dataclass(slots=True)
class Lesson:
    text: str
    state: LessonState
    urgency: dict[int, float]
    focus_reason: str | None
    focus_confidence: float | None = None
    focus_speed: float | None = None
    focus_accuracy: float | None = None

    @property
    def focus_key(self) -> int:
        return next(k.codepoint for k in self.state.keys if k.is_focus)

    @property
    def heatmap(self) -> dict[int, float]:
        return {k.codepoint: k.confidence for k in self.state.keys}


def _lesson_progress(
    layout_name: str,
    layout: Layout,
    stats: dict[int, KeyStats],
    settings: Settings,
    now: float,
    *,
    transitions: dict[str, TransitionStats] | None = None,
) -> tuple[tuple[int, ...], int, LessonState, tuple[int, int] | None]:
    target = target_ms_per_char(settings.target_speed_cpm)
    order = keyboard_order(layout)
    unlocked = compute_unlocked(
        order,
        settings.alphabet_size,
        stats,
        target,
        min_attempts=settings.min_confidence_attempts,
        transitions=transitions,
        min_transition_attempts=settings.min_transition_confidence_attempts,
    )
    focus_bigram = (
        select_focus_transition(
            unlocked,
            transitions,
            target,
            now,
            min_attempts=settings.min_transition_confidence_attempts,
        )
        if transitions else None
    )
    if focus_bigram is not None:
        focus = focus_key_from_transition(*focus_bigram)
    else:
        focus = select_focus(
            unlocked,
            stats,
            target,
            now,
            min_attempts=settings.min_confidence_attempts,
        )

    keys = tuple(
        LessonKey(
            codepoint=cp,
            unlocked=True,
            confidence=confidence_of(
                cp, stats, target, min_attempts=settings.min_confidence_attempts,
            ),
            is_focus=(cp == focus),
        )
        for cp in unlocked
    )
    state = LessonState(
        layout=layout_name,
        keys=keys,
        alphabet_size=settings.alphabet_size,
        target_speed_cpm=settings.target_speed_cpm,
    )
    return unlocked, focus, state, focus_bigram


@dataclass(slots=True)
class BuildLesson:
    layout_repo: LayoutRepository
    aggregates_cache: AggregatesCache
    settings_repo: SettingsRepository
    language_provider: LanguageProvider
    wordlist_store: WordListStore
    rng: Random

    def __call__(self, layout_name: str) -> Lesson:
        settings = self.settings_repo.load()
        layout = self.layout_repo.get(layout_name)
        aggregates = self.aggregates_cache.get(layout_name)
        stats = aggregates.keys if aggregates else {}
        transitions = aggregates.transitions if aggregates else {}
        now = time.time()
        unlocked, focus, state, focus_bigram = _lesson_progress(
            layout_name, layout, stats, settings, now, transitions=transitions,
        )
        target = target_ms_per_char(settings.target_speed_cpm)

        table = self.language_provider.transitions(settings.lang)
        generator = AdaptiveGenerator(table=table, rng=self.rng)
        alphabet_chars = frozenset(chr(cp) for cp in unlocked)
        char_weights = {
            chr(k.codepoint): practice_weight(
                k.confidence,
                urgency=review_urgency(
                    stats[k.codepoint].last_seen if k.codepoint in stats else 0.0, now,
                ),
            )
            for k in state.keys
        }
        char_weights[chr(focus)] *= settings.focus_char_boost
        transition_weights = {
            transition_key(prev, nxt): transition_practice_weight(
                transition_confidence_of(
                    prev,
                    nxt,
                    transitions,
                    target,
                    min_attempts=settings.min_transition_confidence_attempts,
                ),
                urgency=review_urgency(
                    transitions[transition_key(prev, nxt)].last_seen
                    if transition_key(prev, nxt) in transitions else 0.0,
                    now,
                ),
            )
            for prev in unlocked
            for nxt in unlocked
        }
        if focus_bigram is not None:
            prev_cp, next_cp = focus_bigram
            pair_key = transition_key(prev_cp, next_cp)
            transition_weights[pair_key] *= settings.focus_transition_boost
            focus_confidence = transition_confidence_of(
                prev_cp,
                next_cp,
                transitions,
                target,
                min_attempts=settings.min_transition_confidence_attempts,
            )
            if focus_confidence < _CONFIDENCE_GOOD:
                transition_weights[pair_key] *= settings.focus_weak_extra_boost
                char_weights[chr(focus)] *= settings.focus_weak_extra_boost
        elif confidence_of(
            focus, stats, target, min_attempts=settings.min_confidence_attempts,
        ) < _CONFIDENCE_GOOD:
            char_weights[chr(focus)] *= settings.focus_weak_extra_boost
        dict_words: list[str] | None = None
        if settings.wordlist_url:
            cached = self.wordlist_store.load(settings.wordlist_url)
            if cached:
                filtered = words_for_alphabet(cached, alphabet_chars)
                if filtered:
                    dict_words = filtered
        text = generator.generate_lesson(
            alphabet_chars,
            chr(focus),
            word_count=WORD_COUNT,
            char_weights=char_weights,
            layout=layout,
            transition_weights=transition_weights,
            focus_bigram=focus_bigram,
            words=dict_words,
            focus_word_boost=settings.focus_word_boost,
            focus_bigram_word_boost=settings.focus_bigram_word_boost,
        )

        urgency = {
            cp: review_urgency(stats[cp].last_seen if cp in stats else 0.0, now)
            for cp in unlocked
        }
        focus_speed: float | None = None
        focus_accuracy: float | None = None
        if focus_bigram is not None:
            prev_cp, next_cp = focus_bigram
            reason = _focus_reason_transition(
                prev_cp,
                next_cp,
                transitions,
                target,
                now,
                min_attempts=settings.min_transition_confidence_attempts,
            )
            focus_confidence = transition_confidence_of(
                prev_cp,
                next_cp,
                transitions,
                target,
                min_attempts=settings.min_transition_confidence_attempts,
            )
            if reason:
                focus_speed, focus_accuracy = _transition_focus_metrics(
                    prev_cp, next_cp, transitions, target,
                )
        else:
            reason = _focus_reason(
                focus,
                stats,
                target,
                now,
                min_attempts=settings.min_confidence_attempts,
            )
            focus_confidence = confidence_of(
                focus, stats, target, min_attempts=settings.min_confidence_attempts,
            )
            if reason:
                focus_speed, focus_accuracy = _key_focus_metrics(focus, stats, target)
        return Lesson(
            text=text,
            state=state,
            urgency=urgency,
            focus_reason=reason,
            focus_confidence=focus_confidence if reason else None,
            focus_speed=focus_speed,
            focus_accuracy=focus_accuracy,
        )
