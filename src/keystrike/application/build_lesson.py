"""BuildLesson: the adaptive engine — figure out which keys are unlocked,
pick a focus key, and generate practice text for them.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from random import Random

from keystrike.domain.confidence import (
    accuracy_of,
    attempts_of,
    confidence_of,
    is_same_key_transition,
    key_confidence,
    review_urgency,
    round_confidence,
    skill_from_stats,
    skill_of,
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
from keystrike.domain.generator import (
    AdaptiveGenerator,
    LessonWeighting,
    effective_generated_word_bounds,
    effective_lesson_word_count,
    weak_focus_word_quota,
)
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

_CONFIDENCE_GOOD = 1.0


@dataclass(slots=True, frozen=True)
class FocusMetrics:
    speed: float
    accuracy: float


@dataclass(slots=True, frozen=True)
class FocusExplanation:
    reason: FocusReason | None
    speed: float | None = None
    accuracy: float | None = None
    attempts: int | None = None
    min_attempts: int | None = None


@dataclass(slots=True, frozen=True)
class LessonProgress:
    unlocked: tuple[int, ...]
    focus: int
    state: LessonState
    focus_bigram: Bigram | None
    skill_heatmap: dict[int, float]


def _key_focus_metrics(
    focus: int,
    stats: Mapping[int, KeyStats],
    target: float,
) -> FocusMetrics:
    key_stats = stats.get(focus)
    if key_stats is None:
        return FocusMetrics(speed=0.0, accuracy=0.0)
    return FocusMetrics(
        speed=round_confidence(key_confidence(target, key_stats.mean_time_ns)),
        accuracy=round_confidence(accuracy_of(key_stats)),
    )


def _transition_focus_metrics(
    prev_cp: int,
    next_cp: int,
    transitions: Mapping[Bigram, TransitionStats],
    target: float,
) -> FocusMetrics:
    t_stats = transitions.get(Bigram(prev_cp, next_cp))
    if t_stats is None:
        return FocusMetrics(speed=0.0, accuracy=0.0)
    return FocusMetrics(
        speed=round_confidence(transition_confidence(target, t_stats.mean_time_ns)),
        accuracy=round_confidence(transition_accuracy_of(t_stats)),
    )


def _focus_reason_for_confidence(
    confidence: float,
    skill: float,
    urgency: float,
    *,
    weak_kind: FocusKind,
    calibrating_kind: FocusKind,
    review_kind: FocusKind,
    pair: Bigram | None,
) -> FocusReason | None:
    """Shared body for key- and transition-focus reasons — the two only
    differ in which FocusKind pair applies and whether a Bigram is attached."""
    if urgency > 0 and confidence >= _CONFIDENCE_GOOD:
        return FocusReason(kind=review_kind, pair=pair)
    if confidence < _CONFIDENCE_GOOD:
        if skill >= _CONFIDENCE_GOOD:
            return FocusReason(kind=calibrating_kind, pair=pair)
        return FocusReason(kind=weak_kind, pair=pair)
    return None


def _resolve_focus_confidence(
    focus: int,
    focus_bigram: Bigram | None,
    ctx: _LessonContext,
) -> float:
    """The one confidence value the rest of lesson-building keys off of —
    computed once so weighting and the focus-reason explanation agree."""
    if focus_bigram is not None:
        return transition_confidence_of(
            focus_bigram.prev_cp,
            focus_bigram.next_cp,
            ctx.transitions,
            ctx.target,
            min_attempts=ctx.settings.min_transition_confidence_attempts,
        )
    return confidence_of(
        focus,
        ctx.stats,
        ctx.target,
        min_attempts=ctx.settings.min_confidence_attempts,
    )


def _compute_focus_explanation(
    focus: int,
    focus_bigram: Bigram | None,
    focus_confidence: float,
    ctx: _LessonContext,
) -> FocusExplanation:
    """Why (if at all) today's focus is being called out, plus the raw
    speed/accuracy to show alongside it. Reuses `focus_confidence` rather
    than recomputing it (it was already needed for weighting)."""
    if focus_bigram is not None:
        t_stats = ctx.transitions.get(focus_bigram)
        urgency = review_urgency(t_stats.last_seen if t_stats else 0.0, ctx.now)
        skill = skill_from_stats(t_stats, ctx.target)
        reason = _focus_reason_for_confidence(
            focus_confidence,
            skill,
            urgency,
            weak_kind=FocusKind.TRANSITION_WEAK,
            calibrating_kind=FocusKind.TRANSITION_CALIBRATING,
            review_kind=FocusKind.TRANSITION_REVIEW,
            pair=focus_bigram,
        )
        if reason is None:
            return FocusExplanation(reason=None)
        metrics = _transition_focus_metrics(
            focus_bigram.prev_cp,
            focus_bigram.next_cp,
            ctx.transitions,
            ctx.target,
        )
        attempts = attempts_of(t_stats) if t_stats is not None else 0
        return FocusExplanation(
            reason=reason,
            speed=metrics.speed,
            accuracy=metrics.accuracy,
            attempts=attempts,
            min_attempts=ctx.settings.min_transition_confidence_attempts,
        )

    key_stats = ctx.stats.get(focus)
    urgency = review_urgency(key_stats.last_seen if key_stats else 0.0, ctx.now)
    skill = skill_of(focus, ctx.stats, ctx.target)
    reason = _focus_reason_for_confidence(
        focus_confidence,
        skill,
        urgency,
        weak_kind=FocusKind.KEY_WEAK,
        calibrating_kind=FocusKind.KEY_CALIBRATING,
        review_kind=FocusKind.KEY_REVIEW,
        pair=None,
    )
    if reason is None:
        return FocusExplanation(reason=None)
    metrics = _key_focus_metrics(focus, ctx.stats, ctx.target)
    attempts = attempts_of(key_stats) if key_stats is not None else 0
    return FocusExplanation(
        reason=reason,
        speed=metrics.speed,
        accuracy=metrics.accuracy,
        attempts=attempts,
        min_attempts=ctx.settings.min_confidence_attempts,
    )


@dataclass(slots=True)
class Lesson:
    text: str
    state: LessonState
    urgency: dict[int, float]
    focus_reason: FocusReason | None
    skill_heatmap: dict[int, float]
    focus_confidence: float | None = None
    focus_speed: float | None = None
    focus_accuracy: float | None = None
    focus_attempts: int | None = None
    focus_min_attempts: int | None = None

    @property
    def focus_key(self) -> int:
        return next(k.codepoint for k in self.state.keys if k.is_focus)

    @property
    def heatmap(self) -> dict[int, float]:
        return {k.codepoint: k.confidence for k in self.state.keys}


def _lesson_progress(
    layout_name: str,
    ctx: _LessonContext,
) -> LessonProgress:
    order = keyboard_order(ctx.layout)
    unlocked = compute_unlocked(
        order,
        ctx.settings.alphabet_size,
        ctx.stats,
        ctx.target,
        min_attempts=ctx.settings.min_confidence_attempts,
        transitions=ctx.transitions,
        min_transition_attempts=ctx.settings.min_transition_confidence_attempts,
    )
    keys_need_focus = has_weak_unlocked_key(
        unlocked,
        ctx.stats,
        ctx.target,
        threshold=_CONFIDENCE_GOOD,
        min_attempts=ctx.settings.min_confidence_attempts,
    )
    focus_bigram: Bigram | None = None
    if not keys_need_focus and ctx.transitions:
        focus_bigram = select_focus_transition(
            unlocked,
            ctx.transitions,
            ctx.target,
            ctx.now,
            min_attempts=ctx.settings.min_transition_confidence_attempts,
        )

    if focus_bigram is not None:
        focus = focus_key_from_transition(*focus_bigram)
    else:
        focus = select_focus(
            unlocked,
            ctx.stats,
            ctx.target,
            ctx.now,
            min_attempts=ctx.settings.min_confidence_attempts,
        )

    keys = tuple(
        LessonKey(
            codepoint=cp,
            unlocked=True,
            confidence=confidence_of(
                cp,
                ctx.stats,
                ctx.target,
                min_attempts=ctx.settings.min_confidence_attempts,
            ),
            is_focus=(cp == focus),
        )
        for cp in unlocked
    )
    state = LessonState(
        layout=layout_name,
        keys=keys,
        alphabet_size=ctx.settings.alphabet_size,
        target_speed_cpm=ctx.settings.target_speed_cpm,
    )
    return LessonProgress(
        unlocked=unlocked,
        focus=focus,
        state=state,
        focus_bigram=focus_bigram,
        skill_heatmap={cp: skill_of(cp, ctx.stats, ctx.target) for cp in unlocked},
    )


def _compute_weights(
    state: LessonState,
    focus: int,
    focus_bigram: Bigram | None,
    focus_confidence: float,
    *,
    unlocked: tuple[int, ...],
    ctx: _LessonContext,
) -> tuple[dict[str, float], dict[Bigram, float]]:
    """Per-char and per-transition sampling weights for practice-text
    generation, biased toward weak/stale keys and boosted further for
    today's focus (see `domain.focus.practice_weight`)."""
    char_weights = {
        chr(k.codepoint): practice_weight(
            k.confidence,
            urgency=review_urgency(
                ctx.stats[k.codepoint].last_seen if k.codepoint in ctx.stats else 0.0,
                ctx.now,
            ),
        )
        for k in state.keys
    }
    char_weights[chr(focus)] *= ctx.settings.focus_char_boost
    transition_weights = {
        Bigram(prev, nxt): transition_practice_weight(
            transition_confidence_of(
                prev,
                nxt,
                ctx.transitions,
                ctx.target,
                min_attempts=ctx.settings.min_transition_confidence_attempts,
            ),
            urgency=review_urgency(
                ctx.transitions[Bigram(prev, nxt)].last_seen
                if Bigram(prev, nxt) in ctx.transitions
                else 0.0,
                ctx.now,
            ),
        )
        for prev in unlocked
        for nxt in unlocked
        if not is_same_key_transition(prev, nxt)
    }
    if focus_bigram is not None:
        transition_weights[focus_bigram] *= ctx.settings.focus_transition_boost
        if focus_confidence < _CONFIDENCE_GOOD:
            transition_weights[focus_bigram] *= ctx.settings.focus_weak_extra_boost
            char_weights[chr(focus)] *= ctx.settings.focus_weak_extra_boost
    elif focus_confidence < _CONFIDENCE_GOOD:
        char_weights[chr(focus)] *= ctx.settings.focus_weak_extra_boost
    return char_weights, transition_weights


@dataclass(slots=True)
class _LessonContext:
    settings: Settings
    layout: Layout
    stats: Mapping[int, KeyStats]
    transitions: Mapping[Bigram, TransitionStats]
    now: float
    target: float


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
        ctx = self._load_context(layout_name)
        progress = _lesson_progress(layout_name, ctx)
        focus_confidence = _resolve_focus_confidence(progress.focus, progress.focus_bigram, ctx)
        char_weights, transition_weights = _compute_weights(
            progress.state,
            progress.focus,
            progress.focus_bigram,
            focus_confidence,
            unlocked=progress.unlocked,
            ctx=ctx,
        )
        alphabet_chars = frozenset(chr(cp) for cp in progress.unlocked)
        text = self._generate_text(
            ctx,
            alphabet_chars,
            progress.focus,
            progress.focus_bigram,
            focus_confidence=focus_confidence,
            char_weights=char_weights,
            transition_weights=transition_weights,
        )
        urgency = _compute_urgency(ctx.stats, progress.unlocked, ctx.now)
        explanation = _compute_focus_explanation(
            progress.focus, progress.focus_bigram, focus_confidence, ctx
        )
        return Lesson(
            text=text,
            state=progress.state,
            urgency=urgency,
            focus_reason=explanation.reason,
            skill_heatmap=progress.skill_heatmap,
            focus_confidence=focus_confidence if explanation.reason else None,
            focus_speed=explanation.speed,
            focus_accuracy=explanation.accuracy,
            focus_attempts=explanation.attempts,
            focus_min_attempts=explanation.min_attempts,
        )

    def _load_context(self, layout_name: str) -> _LessonContext:
        settings = self.settings_repo.load()
        layout = self.layout_repo.get(layout_name)
        aggregates = self.aggregates_cache.get(layout_name)
        stats: Mapping[int, KeyStats] = aggregates.keys if aggregates else {}
        transitions: Mapping[Bigram, TransitionStats] = aggregates.transitions if aggregates else {}
        return _LessonContext(
            settings=settings,
            layout=layout,
            stats=stats,
            transitions=transitions,
            now=self.clock.wall_epoch(),
            target=target_ms_per_char(settings.target_speed_cpm),
        )

    def _generate_text(
        self,
        ctx: _LessonContext,
        alphabet_chars: frozenset[str],
        focus: int,
        focus_bigram: Bigram | None,
        *,
        focus_confidence: float,
        char_weights: dict[str, float],
        transition_weights: dict[Bigram, float],
    ) -> str:
        table = self.language_provider.transitions(ctx.settings.lang)
        generator = AdaptiveGenerator(table=table, rng=self.rng)
        weighting = LessonWeighting(
            char_weights=char_weights,
            transition_weights=transition_weights,
            layout=ctx.layout,
            words=self._resolve_dict_words(ctx.settings, alphabet_chars),
            focus_word_boost=ctx.settings.focus_word_boost,
            focus_bigram_word_boost=ctx.settings.focus_bigram_word_boost,
        )
        word_count = effective_lesson_word_count(ctx.settings.lesson_word_count)
        quota = (
            weak_focus_word_quota(word_count, ctx.settings.focus_word_min_fraction)
            if focus_confidence < _CONFIDENCE_GOOD
            else 1
        )
        generated_min_len, generated_max_len = effective_generated_word_bounds(
            ctx.settings.generated_word_min_len,
            ctx.settings.generated_word_max_len,
        )
        return generator.generate_lesson(
            alphabet_chars,
            chr(focus),
            word_count=word_count,
            weighting=weighting,
            focus_bigram=focus_bigram,
            min_focus_words=quota,
            max_word_repeats=ctx.settings.max_word_repeats,
            generated_min_len=generated_min_len,
            generated_max_len=generated_max_len,
        )

    def _resolve_dict_words(
        self,
        settings: Settings,
        alphabet_chars: frozenset[str],
    ) -> tuple[str, ...] | None:
        if not settings.wordlist_url:
            return None
        cached = self.wordlist_store.load(settings.wordlist_url)
        if not cached:
            return None
        filtered = words_for_alphabet(cached, alphabet_chars)
        return tuple(filtered) if filtered else None


def _compute_urgency(
    stats: Mapping[int, KeyStats],
    unlocked: tuple[int, ...],
    now: float,
) -> dict[int, float]:
    return {cp: review_urgency(stats[cp].last_seen if cp in stats else 0.0, now) for cp in unlocked}
