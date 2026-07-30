"""BuildLesson: the adaptive engine — figure out which keys are unlocked,
pick a focus key, and generate practice text for them.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from random import Random

from keystrike.domain.confidence import (
    accuracy_of,
    confidence_of,
    is_same_key_transition,
    key_confidence,
    review_urgency,
    round_confidence,
    target_ms_per_char,
    transition_accuracy_of,
    transition_confidence,
    transition_confidence_of,
)
from keystrike.domain.enums import FocusKind
from keystrike.domain.focus import (
    FocusReason,
    focus_key_from_transition,
    has_weak_unlocked_key,
    practice_weight,
    select_focus,
    select_focus_transition,
    transition_practice_weight,
)
from keystrike.domain.generator import AdaptiveGenerator, LessonWeighting
from keystrike.domain.learn_order import keyboard_order
from keystrike.domain.models import (
    Bigram,
    KeyStats,
    Layout,
    LessonKey,
    LessonState,
    Settings,
    TransitionStats,
)
from keystrike.domain.protocols import (
    AggregatesCache,
    Clock,
    LanguageProvider,
    LayoutRepository,
    SettingsRepository,
    WordListStore,
)
from keystrike.domain.unlock import compute_unlocked
from keystrike.domain.wordlist import words_for_alphabet

WORD_COUNT = 12
_CONFIDENCE_GOOD = 1.0


def _key_focus_metrics(
    focus: int,
    stats: Mapping[int, KeyStats],
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
    transitions: Mapping[Bigram, TransitionStats],
    target: float,
) -> tuple[float, float]:
    t_stats = transitions.get(Bigram(prev_cp, next_cp))
    if t_stats is None:
        return 0.0, 0.0
    return (
        round_confidence(transition_confidence(target, t_stats.mean_time_ns)),
        round_confidence(transition_accuracy_of(t_stats)),
    )


def _focus_reason_for_confidence(
    confidence: float,
    urgency: float,
    *,
    weak_kind: FocusKind,
    review_kind: FocusKind,
    pair: Bigram | None,
) -> FocusReason | None:
    """Shared body for key- and transition-focus reasons — the two only
    differ in which FocusKind pair applies and whether a Bigram is attached."""
    if urgency > 0 and confidence >= _CONFIDENCE_GOOD:
        return FocusReason(kind=review_kind, pair=pair)
    if confidence < _CONFIDENCE_GOOD:
        return FocusReason(kind=weak_kind, pair=pair)
    return None


def _resolve_focus_confidence(
    focus: int,
    focus_bigram: Bigram | None,
    *,
    stats: Mapping[int, KeyStats],
    transitions: Mapping[Bigram, TransitionStats],
    target: float,
    settings: Settings,
) -> float:
    """The one confidence value the rest of lesson-building keys off of —
    computed once so weighting and the focus-reason explanation agree."""
    if focus_bigram is not None:
        return transition_confidence_of(
            focus_bigram.prev_cp,
            focus_bigram.next_cp,
            transitions,
            target,
            min_attempts=settings.min_transition_confidence_attempts,
        )
    return confidence_of(focus, stats, target, min_attempts=settings.min_confidence_attempts)


def _compute_focus_explanation(
    focus: int,
    focus_bigram: Bigram | None,
    focus_confidence: float,
    *,
    stats: Mapping[int, KeyStats],
    transitions: Mapping[Bigram, TransitionStats],
    target: float,
    now: float,
) -> tuple[FocusReason | None, float | None, float | None]:
    """Why (if at all) today's focus is being called out, plus the raw
    speed/accuracy to show alongside it. Reuses `focus_confidence` rather
    than recomputing it (it was already needed for weighting)."""
    if focus_bigram is not None:
        t_stats = transitions.get(focus_bigram)
        urgency = review_urgency(t_stats.last_seen if t_stats else 0.0, now)
        reason = _focus_reason_for_confidence(
            focus_confidence,
            urgency,
            weak_kind=FocusKind.TRANSITION_WEAK,
            review_kind=FocusKind.TRANSITION_REVIEW,
            pair=focus_bigram,
        )
        if reason is None:
            return None, None, None
        speed, accuracy = _transition_focus_metrics(
            focus_bigram.prev_cp,
            focus_bigram.next_cp,
            transitions,
            target,
        )
        return reason, speed, accuracy

    key_stats = stats.get(focus)
    urgency = review_urgency(key_stats.last_seen if key_stats else 0.0, now)
    reason = _focus_reason_for_confidence(
        focus_confidence,
        urgency,
        weak_kind=FocusKind.KEY_WEAK,
        review_kind=FocusKind.KEY_REVIEW,
        pair=None,
    )
    if reason is None:
        return None, None, None
    speed, accuracy = _key_focus_metrics(focus, stats, target)
    return reason, speed, accuracy


@dataclass(slots=True)
class Lesson:
    text: str
    state: LessonState
    urgency: dict[int, float]
    focus_reason: FocusReason | None
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
    stats: Mapping[int, KeyStats],
    settings: Settings,
    now: float,
    *,
    transitions: Mapping[Bigram, TransitionStats] | None = None,
) -> tuple[tuple[int, ...], int, LessonState, Bigram | None]:
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
    keys_need_focus = has_weak_unlocked_key(
        unlocked,
        stats,
        target,
        threshold=_CONFIDENCE_GOOD,
        min_attempts=settings.min_confidence_attempts,
    )
    if keys_need_focus:
        focus_bigram = None
        focus = select_focus(
            unlocked,
            stats,
            target,
            now,
            min_attempts=settings.min_confidence_attempts,
        )
    elif transitions:
        focus_bigram = select_focus_transition(
            unlocked,
            transitions,
            target,
            now,
            min_attempts=settings.min_transition_confidence_attempts,
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
    else:
        focus_bigram = None
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
                cp,
                stats,
                target,
                min_attempts=settings.min_confidence_attempts,
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


def _compute_weights(
    state: LessonState,
    focus: int,
    focus_bigram: Bigram | None,
    focus_confidence: float,
    *,
    unlocked: tuple[int, ...],
    stats: Mapping[int, KeyStats],
    transitions: Mapping[Bigram, TransitionStats],
    target: float,
    settings: Settings,
    now: float,
) -> tuple[dict[str, float], dict[Bigram, float]]:
    """Per-char and per-transition sampling weights for practice-text
    generation, biased toward weak/stale keys and boosted further for
    today's focus (see `domain.focus.practice_weight`)."""
    char_weights = {
        chr(k.codepoint): practice_weight(
            k.confidence,
            urgency=review_urgency(
                stats[k.codepoint].last_seen if k.codepoint in stats else 0.0,
                now,
            ),
        )
        for k in state.keys
    }
    char_weights[chr(focus)] *= settings.focus_char_boost
    transition_weights = {
        Bigram(prev, nxt): transition_practice_weight(
            transition_confidence_of(
                prev,
                nxt,
                transitions,
                target,
                min_attempts=settings.min_transition_confidence_attempts,
            ),
            urgency=review_urgency(
                transitions[Bigram(prev, nxt)].last_seen
                if Bigram(prev, nxt) in transitions
                else 0.0,
                now,
            ),
        )
        for prev in unlocked
        for nxt in unlocked
        if not is_same_key_transition(prev, nxt)
    }
    if focus_bigram is not None:
        transition_weights[focus_bigram] *= settings.focus_transition_boost
        if focus_confidence < _CONFIDENCE_GOOD:
            transition_weights[focus_bigram] *= settings.focus_weak_extra_boost
            char_weights[chr(focus)] *= settings.focus_weak_extra_boost
    elif focus_confidence < _CONFIDENCE_GOOD:
        char_weights[chr(focus)] *= settings.focus_weak_extra_boost
    return char_weights, transition_weights


@dataclass(slots=True)
class BuildLesson:
    layout_repo: LayoutRepository
    aggregates_cache: AggregatesCache
    settings_repo: SettingsRepository
    language_provider: LanguageProvider
    wordlist_store: WordListStore
    rng: Random
    clock: Clock

    def __call__(self, layout_name: str) -> Lesson:
        settings = self.settings_repo.load()
        layout = self.layout_repo.get(layout_name)
        aggregates = self.aggregates_cache.get(layout_name)
        stats: Mapping[int, KeyStats] = aggregates.keys if aggregates else {}
        transitions: Mapping[Bigram, TransitionStats] = aggregates.transitions if aggregates else {}
        now = self.clock.wall_epoch()
        unlocked, focus, state, focus_bigram = _lesson_progress(
            layout_name,
            layout,
            stats,
            settings,
            now,
            transitions=transitions,
        )
        target = target_ms_per_char(settings.target_speed_cpm)
        focus_confidence = _resolve_focus_confidence(
            focus,
            focus_bigram,
            stats=stats,
            transitions=transitions,
            target=target,
            settings=settings,
        )

        table = self.language_provider.transitions(settings.lang)
        generator = AdaptiveGenerator(table=table, rng=self.rng)
        alphabet_chars = frozenset(chr(cp) for cp in unlocked)
        char_weights, transition_weights = _compute_weights(
            state,
            focus,
            focus_bigram,
            focus_confidence,
            unlocked=unlocked,
            stats=stats,
            transitions=transitions,
            target=target,
            settings=settings,
            now=now,
        )

        dict_words: tuple[str, ...] | None = None
        if settings.wordlist_url:
            cached = self.wordlist_store.load(settings.wordlist_url)
            if cached:
                filtered = words_for_alphabet(cached, alphabet_chars)
                if filtered:
                    dict_words = tuple(filtered)
        weighting = LessonWeighting(
            char_weights=char_weights,
            transition_weights=transition_weights,
            layout=layout,
            words=dict_words,
            focus_word_boost=settings.focus_word_boost,
            focus_bigram_word_boost=settings.focus_bigram_word_boost,
        )
        text = generator.generate_lesson(
            alphabet_chars,
            chr(focus),
            word_count=WORD_COUNT,
            weighting=weighting,
            focus_bigram=focus_bigram,
        )

        urgency = {
            cp: review_urgency(stats[cp].last_seen if cp in stats else 0.0, now) for cp in unlocked
        }
        reason, focus_speed, focus_accuracy = _compute_focus_explanation(
            focus,
            focus_bigram,
            focus_confidence,
            stats=stats,
            transitions=transitions,
            target=target,
            now=now,
        )
        return Lesson(
            text=text,
            state=state,
            urgency=urgency,
            focus_reason=reason,
            focus_confidence=focus_confidence if reason else None,
            focus_speed=focus_speed,
            focus_accuracy=focus_accuracy,
        )
