"""BuildLesson: the adaptive engine — figure out which keys are unlocked,
pick a focus key, and generate practice text for them.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from random import Random

from keystrike.application.alphabet_sync import sync_alphabet_size
from keystrike.application.session_queries import latest_session_header, target_speed_cpm
from keystrike.domain.advice import (
    NO_CHOICES,
    FocusChoices,
    Kind,
    LessonAdvice,
    apply_focus_advice,
    weigh_advice,
    word_boosts,
)
from keystrike.domain.confidence import (
    CONFIDENCE_GOOD,
    accuracy_of,
    attempts_of,
    clears_threshold,
    confidence_of,
    key_confidence,
    review_urgency,
    round_confidence,
    skill_from_stats,
    skill_of,
    stall_attempts_cap,
    target_ms_per_char,
    transition_accuracy_of,
    transition_confidence,
    transition_confidence_of,
)
from keystrike.domain.enums import FocusKind
from keystrike.domain.focus import (
    FocusReason,
    coverage_deficit_factor,
    practice_weight,
    select_lesson_focus,
)
from keystrike.domain.generator import (
    AdaptiveGenerator,
    LessonWeighting,
    WordBoost,
    effective_generated_word_bounds,
    effective_lesson_word_count,
    weak_focus_word_quota,
)
from keystrike.domain.learn_order import keyboard_order
from keystrike.domain.markov import TransitionTable
from keystrike.domain.models import (
    Bigram,
    KeyStats,
    Layout,
    LessonKey,
    LessonState,
    Settings,
    TransitionStats,
)
from keystrike.domain.newest_key import newest_key_gating_cohort
from keystrike.domain.null_adapters import NullSessionRepository
from keystrike.domain.protocols import (
    AggregatesCache,
    Clock,
    LanguageProvider,
    LayoutRepository,
    SessionRepository,
    SettingsRepository,
    WordListStore,
)
from keystrike.domain.unlock import (
    compute_unlocked,
    gating_bigram_is_ready,
    newest_key_transition_gate_progress,
)
from keystrike.domain.wordlist import words_for_alphabet


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
    gating_bigrams: tuple[Bigram, ...]
    bigram_calibration: tuple[int, int] | None
    skill_heatmap: dict[int, float]
    # What advice may pick as focus at this stage (see `_focus_choices`).
    choices: FocusChoices = NO_CHOICES
    # Name of the advisor that chose `focus` / `focus_bigram`, if any.
    focus_advisor: str | None = None


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
    if urgency > 0 and confidence >= CONFIDENCE_GOOD:
        return FocusReason(kind=review_kind, pair=pair)
    if confidence < CONFIDENCE_GOOD:
        if skill >= CONFIDENCE_GOOD:
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
            min_attempts=ctx.settings.unlock.min_transition_confidence_attempts,
        )
    return confidence_of(
        focus,
        ctx.stats,
        ctx.target,
        min_attempts=ctx.settings.unlock.min_confidence_attempts,
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
        attempts = attempts_of(t_stats) if t_stats is not None else 0
        min_attempts = ctx.settings.unlock.min_transition_confidence_attempts
        if reason is None and attempts < min_attempts:
            reason = FocusReason(kind=FocusKind.TRANSITION_CALIBRATING, pair=focus_bigram)
        if reason is None:
            return FocusExplanation(reason=None)
        metrics = _transition_focus_metrics(
            focus_bigram.prev_cp,
            focus_bigram.next_cp,
            ctx.transitions,
            ctx.target,
        )
        return FocusExplanation(
            reason=reason,
            speed=metrics.speed,
            accuracy=metrics.accuracy,
            attempts=attempts,
            min_attempts=min_attempts,
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
        min_attempts=ctx.settings.unlock.min_confidence_attempts,
    )


@dataclass(slots=True)
class Lesson:
    text: str
    state: LessonState
    focus_reason: FocusReason | None
    skill_heatmap: dict[int, float]
    focus_pair: Bigram | None = None
    focus_confidence: float | None = None
    focus_speed: float | None = None
    focus_accuracy: float | None = None
    focus_attempts: int | None = None
    focus_min_attempts: int | None = None
    bigram_calibration: tuple[int, int] | None = None
    # The advisor whose advice steered this lesson (focus or weights), if any.
    advice_source: str | None = None
    # The recommendation kinds that were applied, for example ("emphasize", "contrast").
    advice_kinds: tuple[str, ...] = ()

    @property
    def focus_key(self) -> int:
        return next(k.codepoint for k in self.state.keys if k.is_focus)

    @property
    def heatmap(self) -> dict[int, float]:
        return {k.codepoint: k.confidence for k in self.state.keys}


@dataclass(slots=True, frozen=True)
class _GatingState:
    unlocked: tuple[int, ...]
    keys_need_focus: bool
    transition_blocked: bool
    gating_bigrams: tuple[Bigram, ...]
    bigram_calibration: tuple[int, int] | None


def _gating_state(ctx: _LessonContext) -> _GatingState:
    order = keyboard_order(ctx.layout)
    stall_cap = stall_attempts_cap(ctx.settings.unlock.min_transition_confidence_attempts)
    unlocked = compute_unlocked(
        order,
        ctx.settings.alphabet_size,
        ctx.stats,
        ctx.target,
        tuning=ctx.settings.unlock,
        transitions=ctx.transitions,
        transition_stall_attempts_cap=stall_cap,
    )
    keys_need_focus = not all(
        clears_threshold(
            ctx.stats.get(cp),
            ctx.target,
            threshold=CONFIDENCE_GOOD,
            min_attempts=ctx.settings.unlock.min_confidence_attempts,
        )
        for cp in unlocked
    )
    cohort = newest_key_gating_cohort(
        unlocked,
        ctx.stats,
        limit=ctx.settings.unlock.gating_bigram_limit,
    )
    ready, total = newest_key_transition_gate_progress(
        unlocked,
        ctx.transitions,
        ctx.target,
        ctx.stats,
        tuning=ctx.settings.unlock,
        stall_attempts_cap=stall_cap,
    )
    transition_blocked = not keys_need_focus and len(unlocked) < len(order) and ready < total
    gating_bigrams = (
        tuple(
            pair
            for pair in cohort
            if not gating_bigram_is_ready(
                pair,
                ctx.transitions,
                ctx.target,
                tuning=ctx.settings.unlock,
                stall_attempts_cap=stall_cap,
            )
        )
        if transition_blocked
        else ()
    )
    return _GatingState(
        unlocked=unlocked,
        keys_need_focus=keys_need_focus,
        transition_blocked=transition_blocked,
        gating_bigrams=gating_bigrams,
        bigram_calibration=(ready, total) if transition_blocked else None,
    )


def _resolve_lesson_focus(
    ctx: _LessonContext,
    gating: _GatingState,
) -> tuple[int, Bigram | None]:
    return select_lesson_focus(
        gating.unlocked,
        ctx.stats,
        ctx.transitions,
        ctx.target,
        ctx.now,
        gate=gating.gating_bigrams,
        last_key=ctx.last_key,
        last_pair=ctx.last_pair,
        min_attempts=ctx.settings.unlock.min_confidence_attempts,
        min_transition_attempts=ctx.settings.unlock.min_transition_confidence_attempts,
    )


def _focus_choices(ctx: _LessonContext, gating: _GatingState) -> FocusChoices:
    """The focus candidates advice may choose from, by the stage of
    `select_lesson_focus` the engine is in. Each stage must finish before
    the next key unlocks, so letting advice reorder work inside a stage
    never delays an unlock:

    1. Uncleared keys exist -- any uncleared key, no pairs.
    2. The newest key's gate pairs block -- only those pairs.
    3./4. Otherwise -- any unlocked key or pair of unlocked keys."""
    if gating.keys_need_focus:
        uncleared = frozenset(
            cp
            for cp in gating.unlocked
            if not clears_threshold(
                ctx.stats.get(cp),
                ctx.target,
                threshold=CONFIDENCE_GOOD,
                min_attempts=ctx.settings.unlock.min_confidence_attempts,
            )
        )
        return FocusChoices(keys=uncleared, pairs=frozenset())
    if gating.gating_bigrams:
        return FocusChoices(keys=frozenset(), pairs=frozenset(gating.gating_bigrams))
    return FocusChoices(keys=frozenset(gating.unlocked), pairs=None)


def _lesson_progress(
    layout_name: str,
    ctx: _LessonContext,
) -> LessonProgress:
    gating = _gating_state(ctx)
    focus, focus_bigram = _resolve_lesson_focus(ctx, gating)
    choices = _focus_choices(ctx, gating)
    keys = tuple(
        LessonKey(
            codepoint=cp,
            unlocked=True,
            confidence=confidence_of(
                cp,
                ctx.stats,
                ctx.target,
                min_attempts=ctx.settings.unlock.min_confidence_attempts,
            ),
            is_focus=(cp == focus),
        )
        for cp in gating.unlocked
    )
    state = LessonState(
        layout=layout_name,
        keys=keys,
        # Not `ctx.settings.alphabet_size` -- `compute_unlocked` may have
        # already grown `gating.unlocked` past that floor (see
        # `alphabet_sync.sync_alphabet_size`), and the lesson must always
        # show exactly as many letters as it actually unlocked.
        alphabet_size=len(gating.unlocked),
        target_speed_cpm=ctx.target_cpm,
    )
    return LessonProgress(
        unlocked=gating.unlocked,
        focus=focus,
        state=state,
        focus_bigram=focus_bigram,
        gating_bigrams=gating.gating_bigrams,
        bigram_calibration=gating.bigram_calibration,
        skill_heatmap={cp: skill_of(cp, ctx.stats, ctx.target) for cp in gating.unlocked},
        choices=choices,
    )


def _compute_weights(
    progress: LessonProgress,
    focus_confidence: float,
    ctx: _LessonContext,
) -> tuple[dict[str, float], dict[Bigram, float]]:
    """Per-char and per-transition sampling weights for practice-text
    generation, biased toward weak/stale keys and boosted further for
    today's focus (see `domain.focus.practice_weight`). Only the newest key's
    gate cohort and the focus pair get transition weights: sessions store
    tallies for those pairs only (`FinishSession`)."""
    focus = progress.focus
    focus_bigram = progress.focus_bigram
    unlocked = progress.unlocked
    min_key_attempts = ctx.settings.unlock.min_confidence_attempts
    min_transition_attempts = ctx.settings.unlock.min_transition_confidence_attempts
    char_weights = {
        chr(k.codepoint): practice_weight(
            k.confidence,
            urgency=review_urgency(
                ctx.stats[k.codepoint].last_seen if k.codepoint in ctx.stats else 0.0,
                ctx.now,
            ),
        )
        * coverage_deficit_factor(
            attempts_of(ctx.stats[k.codepoint]) if k.codepoint in ctx.stats else 0,
            min_attempts=min_key_attempts,
        )
        for k in progress.state.keys
    }
    char_weights[chr(focus)] *= ctx.settings.focus.char_boost
    newest_pairs = newest_key_gating_cohort(
        unlocked,
        ctx.stats,
        limit=ctx.settings.unlock.gating_bigram_limit,
    )
    transition_weights = {
        pair: practice_weight(
            transition_confidence_of(
                pair.prev_cp,
                pair.next_cp,
                ctx.transitions,
                ctx.target,
                min_attempts=min_transition_attempts,
            ),
        )
        * coverage_deficit_factor(
            attempts_of(ctx.transitions[pair]) if pair in ctx.transitions else 0,
            min_attempts=min_transition_attempts,
        )
        for pair in newest_pairs
    }
    if focus_bigram is not None:
        transition_weights.setdefault(
            focus_bigram,
            practice_weight(focus_confidence, urgency=0.0)
            * coverage_deficit_factor(0, min_attempts=min_transition_attempts),
        )
        transition_weights[focus_bigram] *= ctx.settings.focus.transition_boost
        if focus_confidence < CONFIDENCE_GOOD:
            transition_weights[focus_bigram] *= ctx.settings.focus.weak_extra_boost
    if focus_confidence < CONFIDENCE_GOOD:
        char_weights[chr(focus)] *= ctx.settings.focus.weak_extra_boost
    return char_weights, transition_weights


def _apply_advice(progress: LessonProgress, advice: LessonAdvice) -> LessonProgress:
    """Let the advisor act as a tie-breaker for the lesson focus. The pure
    rule is `domain.advice.apply_focus_advice`; this moves the result into
    the lesson's key list."""
    picked = apply_focus_advice(progress.focus, progress.focus_bigram, advice, progress.choices)
    if picked is None:
        return progress
    focus, bigram = picked
    keys = tuple(replace(k, is_focus=(k.codepoint == focus)) for k in progress.state.keys)
    return replace(
        progress,
        focus=focus,
        focus_bigram=bigram,
        state=replace(progress.state, keys=keys),
        focus_advisor=advice.source or None,
    )


def _advice_explanation(
    explanation: FocusExplanation, progress: LessonProgress
) -> FocusExplanation:
    """Mark an advisor-chosen focus as such. It is always called out, even
    when the engine would see no reason to (a cleared key)."""
    if explanation.reason is not None:
        return replace(
            explanation, reason=replace(explanation.reason, advisor=progress.focus_advisor)
        )
    pair = progress.focus_bigram
    kind = FocusKind.TRANSITION_REVIEW if pair is not None else FocusKind.KEY_REVIEW
    return FocusExplanation(
        reason=FocusReason(kind=kind, pair=pair, advisor=progress.focus_advisor)
    )


def _applied_kinds(advice: LessonAdvice | None, progress: LessonProgress) -> tuple[str, ...]:
    """The kinds of recommendation that shaped the lesson. A focus kind counts
    only when the advisor really moved the focus."""
    if advice is None:
        return ()
    focus_kinds = (Kind.FOCUS, Kind.FOCUS_PAIR)
    kinds = (
        r.kind.value
        for r in advice.recommendations
        if r.kind not in focus_kinds or progress.focus_advisor is not None
    )
    return tuple(dict.fromkeys(kinds))


@dataclass(slots=True)
class _LessonContext:
    settings: Settings
    layout: Layout
    stats: Mapping[int, KeyStats]
    transitions: Mapping[Bigram, TransitionStats]
    now: float
    target_cpm: int
    target: float
    table: TransitionTable
    # The last finished session's focus, kept while it still needs work.
    last_key: int | None = None
    last_pair: Bigram | None = None


@dataclass(slots=True)
class BuildLesson:
    layout_repo: LayoutRepository
    aggregates_cache: AggregatesCache
    settings_repo: SettingsRepository
    language_provider: LanguageProvider
    wordlist_store: WordListStore
    rng: Random
    clock: Clock
    session_repo: SessionRepository = field(default_factory=NullSessionRepository)
    # The advice for the next lesson of a layout (`AdviceRunner.current`);
    # steers focus and character weights only. Empty advice changes nothing.
    advice: Callable[[str], LessonAdvice] | None = None

    def __call__(self, layout_name: str) -> Lesson:
        ctx = self._load_context(layout_name)
        progress = _lesson_progress(layout_name, ctx)
        advice = self.advice(layout_name) if self.advice is not None else None
        if advice is not None and not advice.actionable:
            advice = None
        if advice is not None:
            progress = _apply_advice(progress, advice)
        # A new letter opening (via `compute_unlocked`'s mastery-driven
        # growth) must bump Settings.alphabet_size before the lesson below
        # is generated -- never show more letters than Settings reports.
        # The synced Settings feeds back into ctx so nothing downstream
        # reads the now-stale alphabet_size.
        ctx.settings = sync_alphabet_size(ctx.settings, progress.unlocked, self.settings_repo)
        focus_confidence = _resolve_focus_confidence(progress.focus, progress.focus_bigram, ctx)
        char_weights, transition_weights = _compute_weights(progress, focus_confidence, ctx)
        boosts = ()
        if advice is not None:
            boosts = word_boosts(
                advice, effective_lesson_word_count(ctx.settings.lesson_word_count)
            )
            protected = {progress.focus}
            if progress.unlocked:
                protected.add(progress.unlocked[-1])
            char_weights = weigh_advice(char_weights, advice, protected=frozenset(protected))
        alphabet_chars = frozenset(chr(cp) for cp in progress.unlocked)
        text = self._generate_text(
            ctx,
            alphabet_chars,
            progress.focus,
            progress.focus_bigram,
            focus_confidence=focus_confidence,
            char_weights=char_weights,
            transition_weights=transition_weights,
            gating_bigrams=progress.gating_bigrams,
            word_boosts=boosts,
        )
        explanation = _compute_focus_explanation(
            progress.focus, progress.focus_bigram, focus_confidence, ctx
        )
        if progress.focus_advisor is not None:
            explanation = _advice_explanation(explanation, progress)
        return Lesson(
            text=text,
            state=progress.state,
            focus_reason=explanation.reason,
            skill_heatmap=progress.skill_heatmap,
            focus_pair=progress.focus_bigram,
            focus_confidence=focus_confidence if explanation.reason else None,
            focus_speed=explanation.speed,
            focus_accuracy=explanation.accuracy,
            focus_attempts=explanation.attempts,
            focus_min_attempts=explanation.min_attempts,
            bigram_calibration=progress.bigram_calibration,
            advice_source=(advice.source or None) if advice is not None else None,
            advice_kinds=_applied_kinds(advice, progress),
        )

    def _load_context(self, layout_name: str) -> _LessonContext:
        settings = self.settings_repo.load()
        layout = self.layout_repo.get(layout_name)
        aggregates = self.aggregates_cache.get(layout_name)
        last = latest_session_header(self.session_repo, layout_name)
        stats: Mapping[int, KeyStats] = aggregates.keys if aggregates else {}
        transitions: Mapping[Bigram, TransitionStats] = aggregates.transitions if aggregates else {}
        target_cpm = target_speed_cpm(self.session_repo, settings, layout_name)
        return _LessonContext(
            settings=settings,
            layout=layout,
            stats=stats,
            transitions=transitions,
            now=self.clock.wall_epoch(),
            target_cpm=target_cpm,
            target=target_ms_per_char(target_cpm),
            table=self.language_provider.transitions(settings.lang),
            last_key=last.focus_key if last is not None else None,
            last_pair=last.focus_pair if last is not None else None,
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
        gating_bigrams: tuple[Bigram, ...],
        word_boosts: tuple[WordBoost, ...] = (),
    ) -> str:
        generator = AdaptiveGenerator(table=ctx.table, rng=self.rng)
        weighting = LessonWeighting(
            char_weights=char_weights,
            transition_weights=transition_weights,
            layout=ctx.layout,
            words=self._resolve_dict_words(ctx.settings, alphabet_chars),
            focus_word_boost=ctx.settings.focus.word_boost,
            focus_bigram_word_boost=ctx.settings.focus.bigram_word_boost,
            word_boosts=word_boosts,
        )
        word_count = effective_lesson_word_count(ctx.settings.lesson_word_count)
        quota = (
            weak_focus_word_quota(word_count, ctx.settings.focus.word_min_fraction)
            if focus_confidence < CONFIDENCE_GOOD
            else 1
        )
        generated_min_len, generated_max_len = effective_generated_word_bounds(
            ctx.settings.word_gen.min_len,
            ctx.settings.word_gen.max_len,
        )
        return generator.generate_lesson(
            alphabet_chars,
            chr(focus),
            word_count=word_count,
            weighting=weighting,
            focus_bigram=focus_bigram,
            focus_bigrams=tuple(dict.fromkeys((focus_bigram, *gating_bigrams)))
            if focus_bigram is not None
            else gating_bigrams,
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
