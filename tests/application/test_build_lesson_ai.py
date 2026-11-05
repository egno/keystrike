from __future__ import annotations

from random import Random

from keystrike.application.build_lesson import (
    AI_EMPHASIS_WEIGHT,
    AI_REST_WEIGHT,
    BuildLesson,
    LessonProgress,
    _apply_ai_focus,  # pyright: ignore[reportPrivateUsage]
    _apply_ai_weights,  # pyright: ignore[reportPrivateUsage]
)
from keystrike.domain.ai_models import AiAnalysis
from keystrike.domain.models import (
    Bigram,
    KeyStats,
    LayoutAggregates,
    LessonKey,
    LessonState,
    Settings,
)
from keystrike.infrastructure.layout_repo import BUNDLED_LAYOUTS
from tests.fakes import (
    FakeAggregatesCache,
    FakeClock,
    FakeLanguageProvider,
    FakeLayoutRepository,
    FakeSettingsRepository,
    FakeWordListStore,
)


def _builder(
    suggestion: AiAnalysis | None,
    *,
    cache: FakeAggregatesCache | None = None,
) -> BuildLesson:
    return BuildLesson(
        layout_repo=FakeLayoutRepository(dict(BUNDLED_LAYOUTS)),
        aggregates_cache=cache or FakeAggregatesCache(),
        settings_repo=FakeSettingsRepository(Settings()),
        language_provider=FakeLanguageProvider(),
        wordlist_store=FakeWordListStore(),
        rng=Random(0),
        clock=FakeClock(),
        ai_suggestion=(lambda _layout: suggestion) if suggestion is not None else None,
    )


def _unlocked() -> list[int]:
    return [k.codepoint for k in _builder(None)("qwerty").state.keys]


def test_no_suggestion_leaves_lesson_unchanged():
    base = _builder(None)("qwerty")
    same = _builder(AiAnalysis(summary="nothing actionable"))("qwerty")
    assert (same.focus_key, same.focus_pair, same.text) == (
        base.focus_key,
        base.focus_pair,
        base.text,
    )


def test_ai_focus_key_becomes_the_lesson_focus():
    unlocked = _unlocked()
    base_focus = _builder(None)("qwerty").focus_key
    target = next(cp for cp in unlocked if cp != base_focus)
    lesson = _builder(AiAnalysis(focus_key=target))("qwerty")
    assert lesson.focus_key == target
    assert sum(k.is_focus for k in lesson.state.keys) == 1
    assert chr(target) in lesson.text
    assert lesson.focus_reason is not None
    assert lesson.focus_reason.coach


def test_ai_cannot_move_focus_to_an_already_cleared_key_while_others_are_weak():
    unlocked = _unlocked()
    cleared = unlocked[0]
    strong = KeyStats(
        codepoint=cleared,
        samples=200,
        mean_time_ns=50_000_000,
        error_count=0.0,
        last_seen=FakeClock().wall,
        attempt_count=200,
    )
    cache = FakeAggregatesCache({"qwerty": LayoutAggregates(keys={cleared: strong})})
    base = _builder(None, cache=cache)("qwerty")
    assert base.focus_key != cleared
    lesson = _builder(AiAnalysis(focus_key=cleared), cache=cache)("qwerty")
    assert lesson.focus_key == base.focus_key
    assert lesson.focus_reason is None or not lesson.focus_reason.coach


def _progress(
    keys: tuple[int, ...],
    *,
    focus: int,
    coach_keys: frozenset[int],
    coach_pairs: frozenset[Bigram] | None,
) -> LessonProgress:
    return LessonProgress(
        unlocked=keys,
        focus=focus,
        state=LessonState(
            layout="qwerty",
            keys=tuple(
                LessonKey(codepoint=cp, unlocked=True, confidence=0.5, is_focus=cp == focus)
                for cp in keys
            ),
            alphabet_size=len(keys),
            target_speed_cpm=300,
        ),
        focus_bigram=None,
        gating_bigrams=(),
        bigram_calibration=None,
        skill_heatmap={},
        coach_keys=coach_keys,
        coach_pairs=coach_pairs,
    )


A, B, C = ord("a"), ord("b"), ord("c")


def test_ai_pair_focus_needs_a_late_stage_or_a_gate_pair():
    keys = (A, B, C)
    stage1 = _progress(keys, focus=A, coach_keys=frozenset({A, B}), coach_pairs=frozenset())
    assert _apply_ai_focus(stage1, AiAnalysis(focus_pair=Bigram(A, B))) is stage1

    gate = Bigram(C, A)
    stage2 = _progress(keys, focus=A, coach_keys=frozenset(), coach_pairs=frozenset({gate}))
    assert _apply_ai_focus(stage2, AiAnalysis(focus_pair=Bigram(A, B))) is stage2
    assert _apply_ai_focus(stage2, AiAnalysis(focus_key=B)) is stage2
    moved = _apply_ai_focus(stage2, AiAnalysis(focus_pair=gate))
    assert (moved.focus, moved.focus_bigram, moved.coach_focus) == (A, gate, True)

    late = _progress(keys, focus=A, coach_keys=frozenset(keys), coach_pairs=None)
    moved = _apply_ai_focus(late, AiAnalysis(focus_pair=Bigram(B, C)))
    assert (moved.focus, moved.focus_bigram) == (C, Bigram(B, C))
    assert [k.codepoint for k in moved.state.keys if k.is_focus] == [C]


def test_ai_choosing_the_engine_focus_is_not_marked_as_coach():
    progress = _progress((A, B), focus=A, coach_keys=frozenset({A, B}), coach_pairs=None)
    assert _apply_ai_focus(progress, AiAnalysis(focus_key=A)) is progress


def test_ai_cannot_focus_a_locked_key():
    unlocked = set(_unlocked())
    locked = next(cp for cp in BUNDLED_LAYOUTS["qwerty"].learn_order if cp not in unlocked)
    base = _builder(None)("qwerty")
    lesson = _builder(AiAnalysis(focus_key=locked, focus_pair=Bigram(locked, ord("a"))))("qwerty")
    assert lesson.focus_key == base.focus_key
    assert lesson.focus_pair == base.focus_pair


def test_ai_suggestion_does_not_distort_displayed_confidence():
    base = _builder(None)("qwerty")
    lesson = _builder(AiAnalysis(emphasis_keys=(ord("e"),), rest_keys=(ord("t"),)))("qwerty")
    assert lesson.heatmap == base.heatmap


def test_ai_weights_scale_and_never_mutate_the_input():
    weights = {"a": 1.0, "b": 1.0, "c": 1.0}
    out = _apply_ai_weights(weights, AiAnalysis(emphasis_keys=(ord("a"),), rest_keys=(ord("b"),)))
    assert out == {"a": AI_EMPHASIS_WEIGHT, "b": AI_REST_WEIGHT, "c": 1.0}
    assert weights == {"a": 1.0, "b": 1.0, "c": 1.0}


def test_ai_weights_never_ease_off_protected_keys():
    out = _apply_ai_weights(
        {"a": 1.0, "b": 1.0},
        AiAnalysis(rest_keys=(ord("a"), ord("b"))),
        protected=frozenset({ord("b")}),
    )
    assert out == {"a": AI_REST_WEIGHT, "b": 1.0}


def test_ai_weights_ignore_keys_outside_the_lesson():
    out = _apply_ai_weights({"a": 1.0}, AiAnalysis(emphasis_keys=(ord("z"),)))
    assert out == {"a": 1.0}
