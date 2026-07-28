from dataclasses import replace
from random import Random

from keystrike.application.build_lesson import BuildCodeLesson, BuildLesson
from keystrike.domain.models import Settings
from keystrike.infrastructure.layout_repo import BUNDLED_LAYOUTS
from tests.fakes import (
    FakeAggregatesCache,
    FakeCodeSnippetProvider,
    FakeLanguageProvider,
    FakeLayoutRepository,
    FakeSettingsRepository,
)


def _build_lesson(settings: Settings | None = None, rng_seed: int = 0) -> BuildLesson:
    return BuildLesson(
        layout_repo=FakeLayoutRepository(dict(BUNDLED_LAYOUTS)),
        aggregates_cache=FakeAggregatesCache(),
        settings_repo=FakeSettingsRepository(settings or Settings()),
        language_provider=FakeLanguageProvider(),
        rng=Random(rng_seed),
    )


def _build_code_lesson(settings: Settings | None = None, rng_seed: int = 0) -> BuildCodeLesson:
    return BuildCodeLesson(
        layout_repo=FakeLayoutRepository(dict(BUNDLED_LAYOUTS)),
        aggregates_cache=FakeAggregatesCache(),
        settings_repo=FakeSettingsRepository(settings or Settings()),
        code_provider=FakeCodeSnippetProvider(),
        rng=Random(rng_seed),
    )


def test_lesson_text_only_uses_unlocked_alphabet_and_spaces():
    lesson = _build_lesson()("qwerty")
    unlocked_chars = {chr(k.codepoint) for k in lesson.state.keys}
    assert set(lesson.text) <= unlocked_chars | {" "}


def test_lesson_text_contains_focus_char():
    lesson = _build_lesson()("qwerty")
    assert chr(lesson.focus_key) in lesson.text


def test_lesson_focus_key_is_among_unlocked_keys():
    lesson = _build_lesson()("qwerty")
    unlocked = {k.codepoint for k in lesson.state.keys}
    assert lesson.focus_key in unlocked
    assert sum(k.is_focus for k in lesson.state.keys) == 1


def test_lesson_state_reflects_settings():
    settings = Settings(alphabet_size=0.3, target_speed_cpm=250, recover_keys=False)
    lesson = _build_lesson(settings)("qwerty")
    assert lesson.state.layout == "qwerty"
    assert lesson.state.alphabet_size == 0.3
    assert lesson.state.target_speed_cpm == 250
    assert lesson.state.recover_keys is False


def test_cold_start_unlocks_forced_fraction_of_learn_order():
    settings = Settings(alphabet_size=0.5)
    lesson = _build_lesson(settings)("qwerty")
    layout = BUNDLED_LAYOUTS["qwerty"]
    expected_count = round(0.5 * len(layout.learn_order))
    assert len(lesson.state.keys) == expected_count


def test_code_lesson_text_is_one_of_the_snippets():
    provider = FakeCodeSnippetProvider()
    lesson = _build_code_lesson()("qwerty")
    assert lesson.text in provider.snippets()


def test_code_lesson_state_mirrors_build_lesson_progress():
    lesson = _build_code_lesson()("qwerty")
    layout = BUNDLED_LAYOUTS["qwerty"]
    expected_count = round(0.5 * len(layout.learn_order))
    assert len(lesson.state.keys) == expected_count
    assert sum(k.is_focus for k in lesson.state.keys) == 1


def test_lesson_heatmap_maps_unlocked_codepoints_to_confidence():
    lesson = _build_lesson()("qwerty")
    assert lesson.heatmap == {k.codepoint: k.confidence for k in lesson.state.keys}
    assert set(lesson.heatmap) == {k.codepoint for k in lesson.state.keys}


def test_keyboard_order_setting_changes_cold_start_unlocked_set_on_qwerty():
    # Cold start (no stats), alphabet_size=0.3 forces a small enough prefix
    # that frequency-order and row-order genuinely disagree on which keys
    # are in it (QWERTY's home row isn't its most frequent letters).
    settings = Settings(alphabet_size=0.3)
    frequency = _build_lesson(settings)("qwerty")
    row_ordered = _build_lesson(replace(settings, keyboard_order=True))("qwerty")

    frequency_unlocked = {k.codepoint for k in frequency.state.keys}
    row_unlocked = {k.codepoint for k in row_ordered.state.keys}
    assert frequency_unlocked != row_unlocked
