from __future__ import annotations

from random import Random

from keystrike.application.build_lesson import (
    BuildLesson,
    LessonProgress,
    _apply_advice,  # pyright: ignore[reportPrivateUsage]
)
from keystrike.domain.advice import (
    FocusChoices,
    Kind,
    LessonAdvice,
)
from keystrike.domain.models import (
    Bigram,
    KeyStats,
    LayoutAggregates,
    LessonKey,
    LessonState,
    Settings,
)
from keystrike.infrastructure.layout_repo import BUNDLED_LAYOUTS
from tests.advice_helpers import advice, rec
from tests.fakes import (
    FakeAggregatesCache,
    FakeClock,
    FakeLanguageProvider,
    FakeLayoutRepository,
    FakeSettingsRepository,
    FakeWordListStore,
)


def _builder(
    suggestion: LessonAdvice | None,
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
        advice=(lambda _layout: suggestion) if suggestion is not None else None,
    )


def _unlocked() -> list[int]:
    return [k.codepoint for k in _builder(None)("qwerty").state.keys]


def test_no_advice_leaves_lesson_unchanged():
    base = _builder(None)("qwerty")
    same = _builder(LessonAdvice(summary="nothing actionable"))("qwerty")
    assert (same.focus_key, same.focus_pair, same.text) == (
        base.focus_key,
        base.focus_pair,
        base.text,
    )
    assert same.advice_kinds == ()


def test_advice_focus_key_becomes_the_lesson_focus():
    unlocked = _unlocked()
    base_focus = _builder(None)("qwerty").focus_key
    target = next(cp for cp in unlocked if cp != base_focus)
    lesson = _builder(advice(rec(Kind.FOCUS, target), source="rules"))("qwerty")
    assert lesson.focus_key == target
    assert sum(k.is_focus for k in lesson.state.keys) == 1
    assert chr(target) in lesson.text
    assert lesson.focus_reason is not None
    assert lesson.focus_reason.advisor == "rules"
    assert lesson.advice_source == "rules"
    assert lesson.advice_kinds == ("focus",)


def test_advice_cannot_move_focus_to_an_already_cleared_key_while_others_are_weak():
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
    lesson = _builder(advice(rec(Kind.FOCUS, cleared)), cache=cache)("qwerty")
    assert lesson.focus_key == base.focus_key
    assert lesson.focus_reason is None or lesson.focus_reason.advisor is None
    assert lesson.advice_kinds == ()  # a focus that was not applied is not recorded


def _progress(
    keys: tuple[int, ...],
    *,
    focus: int,
    choices: FocusChoices,
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
        choices=choices,
    )


A, B, C = ord("a"), ord("b"), ord("c")


def test_advice_pair_focus_needs_a_late_stage_or_a_gate_pair():
    keys = (A, B, C)
    stage1 = _progress(keys, focus=A, choices=FocusChoices(frozenset({A, B}), frozenset()))
    assert _apply_advice(stage1, advice(rec(Kind.FOCUS_PAIR, A, B))) is stage1

    gate = Bigram(C, A)
    stage2 = _progress(keys, focus=A, choices=FocusChoices(frozenset(), frozenset({gate})))
    assert _apply_advice(stage2, advice(rec(Kind.FOCUS_PAIR, A, B))) is stage2
    assert _apply_advice(stage2, advice(rec(Kind.FOCUS, B))) is stage2
    moved = _apply_advice(stage2, advice(rec(Kind.FOCUS_PAIR, C, A), source="rules"))
    assert (moved.focus, moved.focus_bigram, moved.focus_advisor) == (A, gate, "rules")

    late = _progress(keys, focus=A, choices=FocusChoices(frozenset(keys), None))
    moved = _apply_advice(late, advice(rec(Kind.FOCUS_PAIR, B, C)))
    assert (moved.focus, moved.focus_bigram) == (C, Bigram(B, C))
    assert [k.codepoint for k in moved.state.keys if k.is_focus] == [C]


def test_choosing_the_engine_focus_is_not_marked_as_advised():
    progress = _progress((A, B), focus=A, choices=FocusChoices(frozenset({A, B}), None))
    assert _apply_advice(progress, advice(rec(Kind.FOCUS, A))) is progress


def test_advice_cannot_focus_a_locked_key():
    unlocked = set(_unlocked())
    locked = next(cp for cp in BUNDLED_LAYOUTS["qwerty"].learn_order if cp not in unlocked)
    base = _builder(None)("qwerty")
    lesson = _builder(advice(rec(Kind.FOCUS, locked), rec(Kind.FOCUS_PAIR, locked, ord("a"))))(
        "qwerty"
    )
    assert lesson.focus_key == base.focus_key
    assert lesson.focus_pair == base.focus_pair


def test_advice_does_not_distort_displayed_confidence():
    base = _builder(None)("qwerty")
    lesson = _builder(advice(rec(Kind.EMPHASIZE, ord("e")), rec(Kind.EASE, ord("t"))))("qwerty")
    assert lesson.heatmap == base.heatmap


def test_advice_source_and_kinds_are_recorded_only_when_advice_steers_the_lesson():
    assert _builder(None)("qwerty").advice_source is None
    summary_only = LessonAdvice(source="rules", summary="keep going")
    assert _builder(summary_only)("qwerty").advice_source is None
    weights = advice(
        rec(Kind.EMPHASIZE, ord("e")), rec(Kind.CONTRAST, ord("e"), ord("t")), source="rules"
    )
    lesson = _builder(weights)("qwerty")
    assert lesson.advice_source == "rules"
    assert lesson.advice_kinds == ("emphasize", "contrast")


def test_a_contrast_recommendation_puts_both_keys_into_lesson_words():
    unlocked = _unlocked()
    first, second = unlocked[0], unlocked[1]
    base = _builder(None)("qwerty")

    def both(text: str) -> int:
        return sum(chr(first) in w and chr(second) in w for w in text.split())

    contrast = advice(rec(Kind.CONTRAST, first, second, strength=1.0), source="rules")
    lesson = _builder(contrast)("qwerty")
    reserved = int(len(lesson.text.split()) * 0.2)  # at most 20% of the words are reserved
    assert reserved >= 2
    assert both(lesson.text) >= reserved
    assert both(lesson.text) >= both(base.text)
    assert lesson.focus_key == base.focus_key  # contrast never moves the focus
    assert lesson.advice_kinds == ("contrast",)
