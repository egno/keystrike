from __future__ import annotations

from random import Random

from keystrike.application.build_lesson import (
    AI_EMPHASIS_WEIGHT,
    AI_REST_WEIGHT,
    BuildLesson,
    _apply_ai_weights,  # pyright: ignore[reportPrivateUsage]
)
from keystrike.domain.ai_models import AiAnalysis
from keystrike.domain.models import Bigram, Settings
from keystrike.infrastructure.layout_repo import BUNDLED_LAYOUTS
from tests.fakes import (
    FakeAggregatesCache,
    FakeClock,
    FakeLanguageProvider,
    FakeLayoutRepository,
    FakeSettingsRepository,
    FakeWordListStore,
)


def _builder(suggestion: AiAnalysis | None) -> BuildLesson:
    return BuildLesson(
        layout_repo=FakeLayoutRepository(dict(BUNDLED_LAYOUTS)),
        aggregates_cache=FakeAggregatesCache(),
        settings_repo=FakeSettingsRepository(Settings()),
        language_provider=FakeLanguageProvider(),
        wordlist_store=FakeWordListStore(),
        rng=Random(0),
        clock=FakeClock(),
        ai_suggestion=(lambda: suggestion) if suggestion is not None else None,
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


def test_ai_focus_pair_sets_pair_and_focus_on_second_key():
    unlocked = _unlocked()
    pair = Bigram(unlocked[0], unlocked[1])
    lesson = _builder(AiAnalysis(focus_pair=pair))("qwerty")
    assert lesson.focus_pair == pair
    assert lesson.focus_key == pair.next_cp


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


def test_ai_weights_ignore_keys_outside_the_lesson():
    out = _apply_ai_weights({"a": 1.0}, AiAnalysis(emphasis_keys=(ord("z"),)))
    assert out == {"a": 1.0}
