from random import Random

from keystrike.application.build_lesson import BuildLesson, _transition_focus_metrics
from keystrike.domain.aggregate import _combine_transition_maps_weighted, session_recency_weights
from keystrike.domain.confidence import target_ms_per_char, transition_confidence_of
from keystrike.domain.enums import FocusKind
from keystrike.domain.focus import FocusReason
from keystrike.domain.generator import weak_focus_word_quota, word_matches_focus
from keystrike.domain.learn_order import keyboard_order
from keystrike.domain.models import Bigram, KeyStats, LayoutAggregates, Settings, TransitionStats
from keystrike.domain.unlock import compute_unlocked
from keystrike.infrastructure.layout_repo import BUNDLED_LAYOUTS
from tests.fakes import (
    FakeAggregatesCache,
    FakeClock,
    FakeLanguageProvider,
    FakeLayoutRepository,
    FakeSettingsRepository,
    FakeWordListStore,
)


def _build_lesson(settings: Settings | None = None, rng_seed: int = 0) -> BuildLesson:
    return BuildLesson(
        layout_repo=FakeLayoutRepository(dict(BUNDLED_LAYOUTS)),
        aggregates_cache=FakeAggregatesCache(),
        settings_repo=FakeSettingsRepository(settings or Settings()),
        language_provider=FakeLanguageProvider(),
        wordlist_store=FakeWordListStore(),
        rng=Random(rng_seed),
        clock=FakeClock(),
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
    settings = Settings(alphabet_size=5, target_speed_cpm=250)
    lesson = _build_lesson(settings)("qwerty")
    assert lesson.state.layout == "qwerty"
    assert lesson.state.alphabet_size == 5
    assert lesson.state.target_speed_cpm == 250


def test_cold_start_unlocks_forced_count_of_learn_order():
    settings = Settings(alphabet_size=10)
    lesson = _build_lesson(settings)("qwerty")
    assert len(lesson.state.keys) == 10


def test_alphabet_size_caps_at_learn_order_length():
    layout = BUNDLED_LAYOUTS["qwerty"]
    settings = Settings(alphabet_size=len(layout.learn_order) + 100)
    lesson = _build_lesson(settings)("qwerty")
    assert len(lesson.state.keys) == len(layout.learn_order)


def test_lesson_heatmap_maps_unlocked_codepoints_to_confidence():
    lesson = _build_lesson()("qwerty")
    assert lesson.heatmap == {k.codepoint: k.confidence for k in lesson.state.keys}
    assert set(lesson.heatmap) == {k.codepoint for k in lesson.state.keys}


def test_cold_start_unlocks_row_ordered_prefix_not_frequency_order():
    # QWERTY's home row isn't its most frequent letters, so a small enough
    # forced prefix genuinely disagrees between row-order and frequency-order.
    layout = BUNDLED_LAYOUTS["qwerty"]
    settings = Settings(alphabet_size=5)
    lesson = _build_lesson(settings)("qwerty")

    row_unlocked = {k.codepoint for k in lesson.state.keys}
    expected = set(keyboard_order(layout)[:5])
    frequency_prefix = set(layout.learn_order[:5])

    assert row_unlocked == expected
    assert row_unlocked != frequency_prefix


def test_lesson_prefers_weak_key_over_weak_transition():
    layout = BUNDLED_LAYOUTS["qwerty"]
    order = keyboard_order(layout)
    a, s = order[0], order[1]
    now = 1_700_000_000.0
    fast = 100_000_000.0
    at_target = 200_000_000.0
    slow = 400_000_000.0
    keys = {
        a: KeyStats(a, 10, slow, 0, now, attempt_count=10),
        s: KeyStats(s, 10, at_target, 0, now, attempt_count=10),
    }
    transitions = {
        Bigram(a, a): TransitionStats(a, a, 10, fast, 0, now, attempt_count=10),
        Bigram(a, s): TransitionStats(
            a,
            s,
            10,
            slow,
            0,
            now,
            attempt_count=10,
        ),
        Bigram(s, a): TransitionStats(s, a, 10, fast, 0, now, attempt_count=10),
        Bigram(s, s): TransitionStats(s, s, 10, fast, 0, now, attempt_count=10),
    }
    cache = FakeAggregatesCache(
        by_layout={"qwerty": LayoutAggregates(keys=keys, transitions=transitions)},
    )
    builder = BuildLesson(
        layout_repo=FakeLayoutRepository(dict(BUNDLED_LAYOUTS)),
        aggregates_cache=cache,
        settings_repo=FakeSettingsRepository(Settings(alphabet_size=2)),
        language_provider=FakeLanguageProvider(),
        wordlist_store=FakeWordListStore(),
        rng=Random(0),
        clock=FakeClock(),
    )
    lesson = builder("qwerty")
    assert lesson.focus_reason == FocusReason(kind=FocusKind.KEY_WEAK)


def test_lesson_ignores_weak_same_key_transition_for_focus():
    layout = BUNDLED_LAYOUTS["qwerty"]
    order = keyboard_order(layout)
    a, s = order[0], order[1]
    now = 1_700_000_000.0
    at_target = 200_000_000.0
    keys = {
        a: KeyStats(a, 10, at_target, 0, now, attempt_count=10),
        s: KeyStats(s, 10, at_target, 0, now, attempt_count=10),
    }
    transitions = {
        Bigram(a, a): TransitionStats(
            a,
            a,
            10,
            400_000_000.0,
            0,
            now,
            attempt_count=10,
        ),
        Bigram(a, s): TransitionStats(a, s, 10, at_target, 0, now, attempt_count=10),
        Bigram(s, a): TransitionStats(s, a, 10, at_target, 0, now, attempt_count=10),
        Bigram(s, s): TransitionStats(
            s,
            s,
            10,
            400_000_000.0,
            0,
            now,
            attempt_count=10,
        ),
    }
    cache = FakeAggregatesCache(
        by_layout={"qwerty": LayoutAggregates(keys=keys, transitions=transitions)},
    )
    builder = BuildLesson(
        layout_repo=FakeLayoutRepository(dict(BUNDLED_LAYOUTS)),
        aggregates_cache=cache,
        settings_repo=FakeSettingsRepository(Settings(alphabet_size=2)),
        language_provider=FakeLanguageProvider(),
        wordlist_store=FakeWordListStore(),
        rng=Random(0),
        clock=FakeClock(),
    )
    lesson = builder("qwerty")
    assert lesson.focus_reason is None or lesson.focus_reason.kind in (
        FocusKind.KEY_WEAK,
        FocusKind.KEY_REVIEW,
    )


def test_lesson_uses_transition_focus_when_transitions_weak():
    layout = BUNDLED_LAYOUTS["qwerty"]
    order = keyboard_order(layout)
    a, s = order[0], order[1]
    now = 1_700_000_000.0
    five_days = 5 * 86_400.0
    fast = 100_000_000.0
    at_target = 200_000_000.0
    slow = 400_000_000.0
    keys = {
        a: KeyStats(a, 10, at_target, 0, now, attempt_count=10),
        s: KeyStats(s, 9, at_target, 0, now, attempt_count=9),
    }
    transitions = {
        Bigram(a, a): TransitionStats(a, a, 10, fast, 0, now, attempt_count=10),
        Bigram(a, s): TransitionStats(
            a,
            s,
            10,
            slow,
            0,
            now - five_days,
            attempt_count=10,
        ),
        Bigram(s, a): TransitionStats(s, a, 10, fast, 0, now, attempt_count=10),
        Bigram(s, s): TransitionStats(s, s, 10, fast, 0, now, attempt_count=10),
    }
    cache = FakeAggregatesCache(
        by_layout={"qwerty": LayoutAggregates(keys=keys, transitions=transitions)},
    )
    builder = BuildLesson(
        layout_repo=FakeLayoutRepository(dict(BUNDLED_LAYOUTS)),
        aggregates_cache=cache,
        settings_repo=FakeSettingsRepository(Settings(alphabet_size=2)),
        language_provider=FakeLanguageProvider(),
        wordlist_store=FakeWordListStore(),
        rng=Random(0),
        clock=FakeClock(),
    )
    lesson = builder("qwerty")
    pair_bigram = Bigram(a, s)
    pair = pair_bigram.chars()
    assert lesson.focus_key == s
    assert lesson.focus_reason == FocusReason(kind=FocusKind.TRANSITION_WEAK, pair=pair_bigram)
    assert pair in lesson.text.replace(" ", "")


def test_lesson_uses_transition_focus_for_colemak_two_keys_before_third_unlocks():
    """alphabet_size=2 on Colemak-DH: e+t at skill goal but still calibrating."""
    layout = BUNDLED_LAYOUTS["colemak_dh"]
    order = keyboard_order(layout)
    e, t, a = order[0], order[1], order[2]
    assert chr(e) == "e"
    assert chr(t) == "t"
    now = 1_700_000_000.0
    at_target = 200_000_000.0
    keys = {
        e: KeyStats(e, 8, at_target, 0, now, attempt_count=8),
        t: KeyStats(t, 8, at_target, 0, now, attempt_count=8),
    }
    assert a not in compute_unlocked(order, alphabet_size=2, stats=keys, target=200.0)
    cache = FakeAggregatesCache(
        by_layout={"colemak_dh": LayoutAggregates(keys=keys, transitions={})},
    )
    builder = BuildLesson(
        layout_repo=FakeLayoutRepository(dict(BUNDLED_LAYOUTS)),
        aggregates_cache=cache,
        settings_repo=FakeSettingsRepository(Settings(alphabet_size=2)),
        language_provider=FakeLanguageProvider(),
        wordlist_store=FakeWordListStore(),
        rng=Random(0),
        clock=FakeClock(),
    )
    lesson = builder("colemak_dh")
    pair = Bigram(e, t)
    assert lesson.focus_key == t
    assert lesson.focus_reason == FocusReason(kind=FocusKind.TRANSITION_WEAK, pair=pair)
    assert pair.chars() in lesson.text.replace(" ", "")


def test_lesson_uses_transition_focus_when_newly_unlocked_key_unpracticed():
    layout = BUNDLED_LAYOUTS["qwerty"]
    order = keyboard_order(layout)
    a, s, h, d = order[0], order[1], order[2], order[3]
    now = 1_700_000_000.0
    fast = 100_000_000.0
    at_target = 200_000_000.0
    slow = 400_000_000.0
    keys = {
        a: KeyStats(a, 10, at_target, 0, now, attempt_count=10),
        s: KeyStats(s, 10, at_target, 0, now, attempt_count=10),
        h: KeyStats(h, 10, at_target, 0, now, attempt_count=10),
    }
    unlocked = compute_unlocked(order, alphabet_size=3, stats=keys, target=200.0)
    assert d in unlocked  # auto-unlocked once a,s,h are mastered; d has no stats yet
    transitions = {
        Bigram(a, a): TransitionStats(a, a, 10, fast, 0, now, attempt_count=10),
        Bigram(a, s): TransitionStats(
            a,
            s,
            10,
            slow,
            0,
            now,
            attempt_count=10,
        ),
        Bigram(a, h): TransitionStats(a, h, 10, fast, 0, now, attempt_count=10),
        Bigram(s, a): TransitionStats(s, a, 10, fast, 0, now, attempt_count=10),
        Bigram(s, s): TransitionStats(s, s, 10, fast, 0, now, attempt_count=10),
        Bigram(s, h): TransitionStats(s, h, 10, fast, 0, now, attempt_count=10),
        Bigram(h, a): TransitionStats(h, a, 10, fast, 0, now, attempt_count=10),
        Bigram(h, s): TransitionStats(h, s, 10, fast, 0, now, attempt_count=10),
        Bigram(h, h): TransitionStats(h, h, 10, fast, 0, now, attempt_count=10),
    }
    cache = FakeAggregatesCache(
        by_layout={"qwerty": LayoutAggregates(keys=keys, transitions=transitions)},
    )
    builder = BuildLesson(
        layout_repo=FakeLayoutRepository(dict(BUNDLED_LAYOUTS)),
        aggregates_cache=cache,
        settings_repo=FakeSettingsRepository(Settings(alphabet_size=3)),
        language_provider=FakeLanguageProvider(),
        wordlist_store=FakeWordListStore(),
        rng=Random(0),
        clock=FakeClock(),
    )
    lesson = builder("qwerty")
    pair_bigram = Bigram(a, s)
    assert lesson.focus_key == s
    assert lesson.focus_reason == FocusReason(kind=FocusKind.TRANSITION_WEAK, pair=pair_bigram)


def test_transition_focus_metrics_reports_accuracy_when_speed_measured():
    target = target_ms_per_char(300)
    eo_key = Bigram(ord("e"), ord("o"))
    transitions = {
        eo_key: TransitionStats(
            ord("e"),
            ord("o"),
            0,
            196_000_000.0,
            0,
            1.0,
            attempt_count=1,
        ),
    }
    metrics = _transition_focus_metrics(
        ord("e"),
        ord("o"),
        transitions,
        target,
    )
    assert metrics.speed > 0
    assert metrics.accuracy > 0


def test_build_lesson_eo_not_zero_confidence_when_counts_zeroed():
    """Full BuildLesson path: stale samples=0 must not show 0.00 with speed/acc."""
    layout_name = "colemak_dh"
    layout = BUNDLED_LAYOUTS[layout_name]
    order = keyboard_order(layout)
    now = 1_700_000_000.0
    at_target = 200_000_000.0
    o = order[3]
    keys = {
        cp: KeyStats(
            cp,
            9 if cp == o else 10,
            at_target,
            0,
            now,
            attempt_count=9 if cp == o else 10,
        )
        for cp in order[:4]
    }
    eo_key = Bigram(ord("e"), ord("o"))
    slow = 566_631_000.0
    transitions = {
        eo_key: TransitionStats(
            ord("e"),
            ord("o"),
            0,
            slow,
            0,
            now,
            attempt_count=0,
        ),
    }
    cache = FakeAggregatesCache(
        by_layout={layout_name: LayoutAggregates(keys=keys, transitions=transitions)},
    )
    builder = BuildLesson(
        layout_repo=FakeLayoutRepository(dict(BUNDLED_LAYOUTS)),
        aggregates_cache=cache,
        settings_repo=FakeSettingsRepository(
            Settings(layout=layout_name, alphabet_size=4, target_speed_cpm=104),
        ),
        language_provider=FakeLanguageProvider(),
        wordlist_store=FakeWordListStore(),
        rng=Random(0),
        clock=FakeClock(),
    )
    lesson = builder(layout_name)
    assert lesson.focus_reason == FocusReason(
        kind=FocusKind.TRANSITION_CALIBRATING,
        pair=eo_key,
    )
    assert lesson.focus_speed is not None
    assert lesson.focus_speed >= 1.0
    assert lesson.focus_accuracy == 1.0
    assert lesson.focus_confidence is not None
    assert lesson.focus_confidence > 0.0


def test_weak_transition_focus_confidence_matches_displayed_speed():
    """Sparse recency-weighted eo must not show 0.00 confidence with good speed/acc."""
    target = target_ms_per_char(300)
    eo_key = Bigram(ord("e"), ord("o"))
    old = TransitionStats(
        ord("e"),
        ord("o"),
        1,
        196_000_000.0,
        0,
        1.0,
        attempt_count=1,
    )
    empty = TransitionStats(ord("e"), ord("o"), 0, 0.0, 0, 2.0, attempt_count=0)
    merged = _combine_transition_maps_weighted(
        [{eo_key: old}, {eo_key: empty}, {eo_key: empty}],
        session_recency_weights(3),
    )[eo_key]
    metrics = _transition_focus_metrics(
        ord("e"),
        ord("o"),
        {eo_key: merged},
        target,
    )
    confidence = transition_confidence_of(
        ord("e"),
        ord("o"),
        {eo_key: merged},
        target,
    )
    assert metrics.speed >= 1.0
    assert metrics.accuracy == 1.0
    assert confidence > 0.0
    assert confidence < 1.0  # still weak due to sample ramp


def test_lesson_falls_back_to_key_focus_without_transitions():
    layout = BUNDLED_LAYOUTS["qwerty"]
    focus = keyboard_order(layout)[0]
    lesson = _build_lesson(Settings(alphabet_size=1))("qwerty")
    assert lesson.focus_key == focus
    assert lesson.focus_reason == FocusReason(kind=FocusKind.KEY_WEAK)


def test_lesson_uses_transition_review_when_stale_and_mastered():
    layout = BUNDLED_LAYOUTS["qwerty"]
    order = keyboard_order(layout)
    a, s, h = order[0], order[1], order[2]
    now = 1_700_000_000.0
    five_days = 5 * 86_400.0
    at_target = 200_000_000.0
    # s→h stays weak; h still calibrating so unlock stops at a,s,h. Stale a→s
    # wins transition focus via review scoring (see test_select_focus_transition_*).
    slow = 380_000_000.0
    keys = {
        a: KeyStats(a, 10, at_target, 0, now, attempt_count=10),
        s: KeyStats(s, 10, at_target, 0, now, attempt_count=10),
        h: KeyStats(h, 9, at_target, 0, now, attempt_count=9),
    }
    transitions = {
        Bigram(a, a): TransitionStats(
            a,
            a,
            10,
            at_target,
            0,
            now,
            attempt_count=10,
        ),
        Bigram(a, s): TransitionStats(
            a,
            s,
            10,
            at_target,
            0,
            now - five_days,
            attempt_count=10,
        ),
        Bigram(a, h): TransitionStats(
            a,
            h,
            10,
            at_target,
            0,
            now,
            attempt_count=10,
        ),
        Bigram(s, a): TransitionStats(
            s,
            a,
            10,
            at_target,
            0,
            now,
            attempt_count=10,
        ),
        Bigram(s, s): TransitionStats(
            s,
            s,
            10,
            at_target,
            0,
            now,
            attempt_count=10,
        ),
        Bigram(s, h): TransitionStats(
            s,
            h,
            10,
            slow,
            0,
            now,
            attempt_count=10,
        ),
        Bigram(h, a): TransitionStats(
            h,
            a,
            10,
            at_target,
            0,
            now,
            attempt_count=10,
        ),
        Bigram(h, s): TransitionStats(
            h,
            s,
            10,
            at_target,
            0,
            now,
            attempt_count=10,
        ),
        Bigram(h, h): TransitionStats(
            h,
            h,
            10,
            at_target,
            0,
            now,
            attempt_count=10,
        ),
    }
    cache = FakeAggregatesCache(
        by_layout={"qwerty": LayoutAggregates(keys=keys, transitions=transitions)},
    )
    builder = BuildLesson(
        layout_repo=FakeLayoutRepository(dict(BUNDLED_LAYOUTS)),
        aggregates_cache=cache,
        settings_repo=FakeSettingsRepository(Settings(alphabet_size=3)),
        language_provider=FakeLanguageProvider(),
        wordlist_store=FakeWordListStore(),
        rng=Random(0),
        clock=FakeClock(),
    )
    lesson = builder("qwerty")
    assert lesson.focus_key == s
    assert lesson.focus_reason == FocusReason(kind=FocusKind.TRANSITION_REVIEW, pair=Bigram(a, s))


def test_lesson_wordlist_biases_weak_transition():
    layout = BUNDLED_LAYOUTS["qwerty"]
    order = keyboard_order(layout)
    a, s = order[0], order[1]
    now = 1_700_000_000.0
    five_days = 5 * 86_400.0
    fast = 100_000_000.0
    at_target = 200_000_000.0
    slow = 400_000_000.0
    keys = {
        a: KeyStats(a, 10, at_target, 0, now, attempt_count=10),
        s: KeyStats(s, 9, at_target, 0, now, attempt_count=9),
    }
    transitions = {
        Bigram(a, a): TransitionStats(a, a, 10, fast, 0, now, attempt_count=10),
        Bigram(a, s): TransitionStats(
            a,
            s,
            10,
            slow,
            0,
            now - five_days,
            attempt_count=10,
        ),
        Bigram(s, a): TransitionStats(s, a, 10, fast, 0, now, attempt_count=10),
        Bigram(s, s): TransitionStats(s, s, 10, fast, 0, now, attempt_count=10),
    }
    url = "https://example.com/words.txt"
    cached = ["asa", "ass", "sas", "ssa"]
    cache = FakeAggregatesCache(
        by_layout={"qwerty": LayoutAggregates(keys=keys, transitions=transitions)},
    )
    settings = Settings(alphabet_size=2, wordlist_url=url)
    builder = BuildLesson(
        layout_repo=FakeLayoutRepository(dict(BUNDLED_LAYOUTS)),
        aggregates_cache=cache,
        settings_repo=FakeSettingsRepository(settings),
        language_provider=FakeLanguageProvider(),
        wordlist_store=FakeWordListStore(by_url={url: cached}),
        rng=Random(0),
        clock=FakeClock(),
    )
    lesson = builder("qwerty")
    pair = chr(a) + chr(s)
    assert lesson.focus_reason == FocusReason(kind=FocusKind.TRANSITION_WEAK, pair=Bigram(a, s))
    words = lesson.text.split()
    quota = weak_focus_word_quota(settings.lesson_word_count, settings.focus_word_min_fraction)
    bigram_words = sum(1 for word in words if pair in word)
    assert bigram_words >= quota
    assert max(words.count(w) for w in set(words)) <= 2

    ssa_count = 0
    as_word_count = 0
    for seed in range(50):
        builder.rng = Random(seed)
        for word in builder("qwerty").text.split():
            if word == "ssa":
                ssa_count += 1
            elif pair in word:
                as_word_count += 1
    assert as_word_count + ssa_count == 50 * Settings().lesson_word_count
    assert as_word_count > ssa_count * 2


def test_weak_transition_focus_over_represented_in_lesson_words():
    """Weak focus bigram should land in many lesson words, not just the injected one."""
    layout = BUNDLED_LAYOUTS["qwerty"]
    order = keyboard_order(layout)
    a, s = order[0], order[1]
    now = 1_700_000_000.0
    fast = 100_000_000.0
    at_target = 200_000_000.0
    slow = 400_000_000.0
    keys = {
        a: KeyStats(a, 10, at_target, 0, now, attempt_count=10),
        s: KeyStats(s, 9, at_target, 0, now, attempt_count=9),
    }
    transitions = {
        Bigram(a, a): TransitionStats(a, a, 10, fast, 0, now, attempt_count=10),
        Bigram(a, s): TransitionStats(
            a,
            s,
            10,
            slow,
            0,
            now,
            attempt_count=10,
        ),
        Bigram(s, a): TransitionStats(s, a, 10, fast, 0, now, attempt_count=10),
        Bigram(s, s): TransitionStats(s, s, 10, fast, 0, now, attempt_count=10),
    }
    cache = FakeAggregatesCache(
        by_layout={"qwerty": LayoutAggregates(keys=keys, transitions=transitions)},
    )
    builder = BuildLesson(
        layout_repo=FakeLayoutRepository(dict(BUNDLED_LAYOUTS)),
        aggregates_cache=cache,
        settings_repo=FakeSettingsRepository(Settings(alphabet_size=2)),
        language_provider=FakeLanguageProvider(),
        wordlist_store=FakeWordListStore(),
        rng=Random(0),
        clock=FakeClock(),
    )
    pair = chr(a) + chr(s)
    bigram_words = 0
    total_words = 0
    for seed in range(100):
        builder.rng = Random(seed)
        words = builder("qwerty").text.split()
        total_words += len(words)
        bigram_words += sum(1 for word in words if pair in word)
    rate = bigram_words / total_words
    assert rate >= 0.25, f"focus bigram in {rate:.1%} of words, expected >= 25%"


def test_lesson_uses_cached_wordlist_when_configured():
    url = "https://example.com/words.txt"
    cached = ["the", "and", "for", "are", "but", "not", "you", "all"]
    settings = Settings(wordlist_url=url, alphabet_size=26)
    store = FakeWordListStore(by_url={url: cached})
    builder = BuildLesson(
        layout_repo=FakeLayoutRepository(dict(BUNDLED_LAYOUTS)),
        aggregates_cache=FakeAggregatesCache(),
        settings_repo=FakeSettingsRepository(settings),
        language_provider=FakeLanguageProvider(),
        wordlist_store=store,
        rng=Random(42),
        clock=FakeClock(),
    )
    lesson = builder("qwerty")
    words = lesson.text.split()
    from_wordlist = [w for w in words if w in cached]
    assert len(from_wordlist) >= settings.lesson_word_count // 2
    assert max(words.count(w) for w in set(words)) <= 2


def test_weak_key_focus_meets_word_quota_in_build_lesson():
    """Weak key confidence wires min_focus_words=ceil(0.6 * word_count)."""
    layout = BUNDLED_LAYOUTS["qwerty"]
    order = keyboard_order(layout)
    focus_cp = order[0]
    now = 1_700_000_000.0
    slow = 400_000_000.0
    keys = {focus_cp: KeyStats(focus_cp, 10, slow, 0, now, attempt_count=10)}
    cache = FakeAggregatesCache(
        by_layout={"qwerty": LayoutAggregates(keys=keys, transitions={})},
    )
    builder = BuildLesson(
        layout_repo=FakeLayoutRepository(dict(BUNDLED_LAYOUTS)),
        aggregates_cache=cache,
        settings_repo=FakeSettingsRepository(Settings(alphabet_size=1)),
        language_provider=FakeLanguageProvider(),
        wordlist_store=FakeWordListStore(),
        rng=Random(0),
        clock=FakeClock(),
    )
    settings = Settings()
    quota = weak_focus_word_quota(settings.lesson_word_count, settings.focus_word_min_fraction)
    focus_char = chr(focus_cp)
    for seed in range(30):
        builder.rng = Random(seed)
        lesson = builder("qwerty")
        assert lesson.focus_reason == FocusReason(kind=FocusKind.KEY_WEAK)
        words = lesson.text.split()
        focus_words = sum(
            1 for w in words if word_matches_focus(w, focus_char=focus_char, focus_bigram=None)
        )
        assert focus_words >= quota, f"seed={seed}: {focus_words}/{len(words)} focus words"


def test_build_lesson_survives_invalid_focus_word_min_fraction():
    """Hand-edited settings.toml can set fraction outside (0, 1]; quota must clamp."""
    layout = BUNDLED_LAYOUTS["qwerty"]
    order = keyboard_order(layout)
    focus_cp = order[0]
    now = 1_700_000_000.0
    slow = 400_000_000.0
    keys = {focus_cp: KeyStats(focus_cp, 10, slow, 0, now, attempt_count=10)}
    cache = FakeAggregatesCache(
        by_layout={"qwerty": LayoutAggregates(keys=keys, transitions={})},
    )
    settings = Settings(alphabet_size=1, focus_word_min_fraction=1.5)
    builder = BuildLesson(
        layout_repo=FakeLayoutRepository(dict(BUNDLED_LAYOUTS)),
        aggregates_cache=cache,
        settings_repo=FakeSettingsRepository(settings),
        language_provider=FakeLanguageProvider(),
        wordlist_store=FakeWordListStore(),
        rng=Random(0),
        clock=FakeClock(),
    )
    for seed in range(10):
        builder.rng = Random(seed)
        lesson = builder("qwerty")
        assert lesson.focus_reason == FocusReason(kind=FocusKind.KEY_WEAK)
        assert len(lesson.text.split()) == settings.lesson_word_count


def test_build_lesson_markov_respects_generated_word_bounds_from_settings():
    """Settings.generated_word_* must reach the generator on the Markov path."""
    settings = Settings(
        generated_word_min_len=2,
        generated_word_max_len=4,
        wordlist_url="",
        alphabet_size=8,
    )
    builder = _build_lesson(settings)
    for seed in range(30):
        builder.rng = Random(seed)
        words = builder("qwerty").text.split()
        for word in words:
            assert 2 <= len(word) <= 4, f"seed={seed}: {word!r}"


def test_build_lesson_wordlist_uses_dictionary_bounds_not_generated():
    """Imported words use dictionary 3-10 bounds; Markov fill uses generated 2-4."""
    url = "https://example.com/words.txt"
    cached = ["the", "and", "for", "are", "but", "not", "you", "all", "because"]
    settings = Settings(
        generated_word_min_len=2,
        generated_word_max_len=4,
        wordlist_url=url,
        alphabet_size=26,
    )
    builder = BuildLesson(
        layout_repo=FakeLayoutRepository(dict(BUNDLED_LAYOUTS)),
        aggregates_cache=FakeAggregatesCache(),
        settings_repo=FakeSettingsRepository(settings),
        language_provider=FakeLanguageProvider(),
        wordlist_store=FakeWordListStore(by_url={url: cached}),
        rng=Random(42),
        clock=FakeClock(),
    )
    words = builder("qwerty").text.split()
    dict_words = [w for w in words if w in cached]
    assert len(dict_words) >= settings.lesson_word_count // 2
    assert all(3 <= len(w) <= 10 for w in dict_words)
    markov_words = [w for w in words if w not in cached]
    assert all(2 <= len(w) <= 4 for w in markov_words)


def test_lesson_falls_back_to_markov_when_cache_missing():
    url = "https://example.com/words.txt"
    exclusive = ["abcd"] * 20
    settings = Settings(wordlist_url=url, alphabet_size=26)
    with_cache = BuildLesson(
        layout_repo=FakeLayoutRepository(dict(BUNDLED_LAYOUTS)),
        aggregates_cache=FakeAggregatesCache(),
        settings_repo=FakeSettingsRepository(settings),
        language_provider=FakeLanguageProvider(),
        wordlist_store=FakeWordListStore(by_url={url: exclusive}),
        rng=Random(42),
        clock=FakeClock(),
    )
    assert "abcd" in with_cache("qwerty").text

    without_cache = BuildLesson(
        layout_repo=FakeLayoutRepository(dict(BUNDLED_LAYOUTS)),
        aggregates_cache=FakeAggregatesCache(),
        settings_repo=FakeSettingsRepository(settings),
        language_provider=FakeLanguageProvider(),
        wordlist_store=FakeWordListStore(),
        rng=Random(42),
        clock=FakeClock(),
    )
    assert "abcd" not in without_cache("qwerty").text


def test_lesson_falls_back_when_alphabet_filters_all_words():
    url = "https://example.com/words.txt"
    cached = ["zzzzzz", "zzzzzzz", "zzzzzzzz"]
    settings = Settings(wordlist_url=url, alphabet_size=8)
    store = FakeWordListStore(by_url={url: cached})
    builder = BuildLesson(
        layout_repo=FakeLayoutRepository(dict(BUNDLED_LAYOUTS)),
        aggregates_cache=FakeAggregatesCache(),
        settings_repo=FakeSettingsRepository(settings),
        language_provider=FakeLanguageProvider(),
        wordlist_store=store,
        rng=Random(42),
        clock=FakeClock(),
    )
    lesson = builder("qwerty")
    assert all("z" not in word for word in lesson.text.split())


def test_lesson_uses_markov_when_url_saved_without_cache():
    url = "https://example.com/words.txt"
    settings = Settings(wordlist_url=url, alphabet_size=26)
    builder = BuildLesson(
        layout_repo=FakeLayoutRepository(dict(BUNDLED_LAYOUTS)),
        aggregates_cache=FakeAggregatesCache(),
        settings_repo=FakeSettingsRepository(settings),
        language_provider=FakeLanguageProvider(),
        wordlist_store=FakeWordListStore(),
        rng=Random(0),
        clock=FakeClock(),
    )
    lesson = builder("qwerty")
    assert lesson.text
    assert all(
        set(word) <= {chr(k.codepoint) for k in lesson.state.keys} for word in lesson.text.split()
    )


def test_lesson_boosts_coverage_starved_key_among_mastered_alphabet():
    """Under-sampled keys get extra weight vs fully-sampled mastered keys."""
    layout = BUNDLED_LAYOUTS["qwerty"]
    order = keyboard_order(layout)
    now = 1_700_000_000.0
    at_target = 200_000_000.0
    min_attempts = 10
    alphabet_size = 30
    unlocked = order[:alphabet_size]
    starved = unlocked[-1]
    keys = {
        cp: KeyStats(cp, 10, at_target, 0, now, attempt_count=min_attempts) for cp in unlocked[:-1]
    }
    keys[starved] = KeyStats(starved, 3, at_target, 0, now, attempt_count=3)
    cache = FakeAggregatesCache(
        by_layout={"qwerty": LayoutAggregates(keys=keys, transitions={})},
    )
    settings = Settings(alphabet_size=alphabet_size, min_confidence_attempts=min_attempts)
    builder = BuildLesson(
        layout_repo=FakeLayoutRepository(dict(BUNDLED_LAYOUTS)),
        aggregates_cache=cache,
        settings_repo=FakeSettingsRepository(settings),
        language_provider=FakeLanguageProvider(),
        wordlist_store=FakeWordListStore(),
        rng=Random(0),
        clock=FakeClock(),
    )
    starved_char = chr(starved)
    starved_hits = 0
    total_chars = 0
    for seed in range(50):
        builder.rng = Random(seed)
        text = builder("qwerty").text.replace(" ", "")
        total_chars += len(text)
        starved_hits += text.count(starved_char)
    share = starved_hits / total_chars
    expected_uniform = 1 / alphabet_size
    assert share > expected_uniform * 2, (
        f"starved key share {share:.1%} vs uniform {expected_uniform:.1%}"
    )


def test_large_alphabet_unlock_advances_when_keys_rotated():
    """26+ keys with sparse window stats still unlock next key once all meet floor."""
    layout = BUNDLED_LAYOUTS["qwerty"]
    order = keyboard_order(layout)
    now = 1_700_000_000.0
    at_target = 200_000_000.0
    min_attempts = 3
    forced = 26
    target = target_ms_per_char(300)
    stats: dict[int, KeyStats] = {
        cp: KeyStats(cp, 0, at_target, 0, now, attempt_count=0) for cp in order[:forced]
    }
    assert len(compute_unlocked(order, forced, stats, target, min_attempts=min_attempts)) == forced
    for i, cp in enumerate(order[:forced]):
        stats[cp] = KeyStats(cp, 0, at_target, 0, now, attempt_count=min_attempts)
        unlocked = compute_unlocked(order, forced, stats, target, min_attempts=min_attempts)
        if i < forced - 1:
            assert len(unlocked) == forced
        else:
            assert len(unlocked) == forced + 1
            assert unlocked[-1] == order[forced]
