from __future__ import annotations

from dataclasses import replace

import pytest

from keystrike.domain.advice import (
    DEFAULT_RECENCY_DECAY,
    EASE_RANGE,
    EMPHASIS_RANGE,
    MAX_PER_KIND,
    MAX_SUMMARY_CHARS,
    ON_TRACK,
    AdvisorConfig,
    CourseState,
    FocusChoices,
    Kind,
    LessonAdvice,
    Reason,
    RecentTally,
    apply_focus_advice,
    error_rate_ranked,
    format_char,
    neighbors,
    render_summary,
    session_weights,
    validate_advice,
    weigh_advice,
    word_boosts,
)
from keystrike.domain.enums import Finger, Hand
from keystrike.domain.models import Bigram, KeyPos, KeyTally
from tests.advice_helpers import advice, rec

A, B, C, D, E, F, G, Z = (ord(c) for c in "abcdefgz")
FULL = {k: 1.0 for k in (A, B, C, D, E, F, G)}
COURSE = CourseState(unlocked=(A, B, C, D, E, F, G), target_cpm=200, confidence=FULL)


def _valid(*recs):
    return validate_advice(advice(*recs), COURSE)


def test_actionable_needs_a_recommendation():
    assert not LessonAdvice().actionable
    assert not LessonAdvice(summary="hi").actionable
    assert advice(rec(Kind.FOCUS, A)).actionable


def test_newest_is_the_last_unlocked_key():
    assert COURSE.newest == G
    assert CourseState(unlocked=(), target_cpm=0, confidence={}).newest is None


# --- validation ---------------------------------------------------------------


def test_a_locked_key_drops_the_whole_recommendation():
    out = _valid(
        rec(Kind.FOCUS, Z),
        rec(Kind.FOCUS_PAIR, A, Z),
        rec(Kind.CONTRAST, A, Z),
        rec(Kind.EMPHASIZE, Z),
        rec(Kind.EASE, Z),
        rec(Kind.EMPHASIZE, A),
    )
    assert [(r.kind, r.keys) for r in out.recommendations] == [(Kind.EMPHASIZE, (A,))]


@pytest.mark.parametrize(
    "bad",
    [
        rec(Kind.FOCUS, A, B),  # one key only
        rec(Kind.FOCUS_PAIR, A),  # two keys
        rec(Kind.FOCUS_PAIR, A, A),  # not a pair of one key
        rec(Kind.CONTRAST, A, A),
        rec(Kind.EMPHASIZE),
        rec(Kind.EMPHASIZE, A, B),  # one key only, never trimmed
        rec(Kind.EMPHASIZE, A, A),
        rec(Kind.EASE),
        rec(Kind.EASE, A, B),
        rec(Kind.FOCUS, A, A),
    ],
)
def test_wrong_arity_is_dropped(bad):
    assert not _valid(bad).recommendations


def test_ease_needs_reason_mastered_confidence_and_never_the_newest_key():
    out = _valid(rec(Kind.EASE, A), rec(Kind.EASE, G))
    assert [r.keys for r in out.recommendations] == [(A,)]  # G is the newest
    assert not _valid(rec(Kind.EASE, A, reason=Reason.ACCURACY)).recommendations
    assert not _valid(rec(Kind.EASE, A, reason=Reason.SPEED)).recommendations
    weak = CourseState(unlocked=(A, B, G), target_cpm=200, confidence={A: 0.9, B: 1.0, G: 1.0})
    kept = validate_advice(advice(rec(Kind.EASE, A), rec(Kind.EASE, B)), weak)
    assert [r.keys for r in kept.recommendations] == [(B,)]  # A is not mastered


def test_evidence_below_the_floor_is_dropped():
    assert not _valid(rec(Kind.EMPHASIZE, A, events=1)).recommendations
    assert not _valid(rec(Kind.EMPHASIZE, A, events=5, opportunities=9)).recommendations
    assert _valid(rec(Kind.EMPHASIZE, A, events=2, opportunities=10)).recommendations


def test_ease_counts_correct_presses_as_its_events():
    assert not _valid(rec(Kind.EASE, A, events=0, opportunities=20)).recommendations
    assert _valid(rec(Kind.EASE, A, events=40, opportunities=40)).recommendations
    assert not _valid(rec(Kind.EASE, A, events=40, opportunities=9)).recommendations


def test_weak_evidence_has_weak_effect():
    two = _valid(rec(Kind.FOCUS, A, strength=1.0, events=2)).recommendations[0]
    three = _valid(rec(Kind.CONTRAST, A, B, strength=1.0, events=3)).recommendations[0]
    five = _valid(rec(Kind.CONTRAST, A, B, strength=1.0, events=5)).recommendations[0]
    many = _valid(rec(Kind.CONTRAST, A, B, strength=1.0, events=50)).recommendations[0]
    assert two.applied == pytest.approx(0.4)
    assert three.applied == pytest.approx(0.6)
    assert five.applied == pytest.approx(1.0)
    assert many.applied == pytest.approx(1.0)  # evidence beyond 5 events adds nothing


def test_applied_is_recomputed_from_strength_so_validation_is_idempotent():
    once = _valid(rec(Kind.EMPHASIZE, A, strength=0.5, events=3))
    assert validate_advice(once, COURSE) == once


def test_strength_is_clamped_and_zero_strength_is_dropped():
    out = _valid(rec(Kind.EMPHASIZE, A, strength=7.0), rec(Kind.EMPHASIZE, B, strength=-1.0))
    assert [(r.keys, r.applied) for r in out.recommendations] == [((A,), 1.0)]


def test_budget_keeps_the_strongest_recommendations_whole():
    many = [rec(Kind.EMPHASIZE, k, strength=0.5 + i / 20) for i, k in enumerate((A, B, C, D, E))]
    out = _valid(*many)
    assert [r.keys for r in out.recommendations] == [(E,), (D,), (C,)]  # ceil(7 / 3) = 3


def test_budget_keeps_the_strongest_recommendation_per_key():
    out = _valid(
        rec(Kind.EMPHASIZE, A, strength=0.9),
        rec(Kind.EMPHASIZE, A, reason=Reason.SPEED, strength=0.8),
        rec(Kind.EMPHASIZE, A, strength=0.7),
        rec(Kind.EMPHASIZE, B, strength=0.6),
        rec(Kind.EMPHASIZE, C, strength=0.5),
    )
    assert [(r.keys, r.applied) for r in out.recommendations] == [
        ((A,), pytest.approx(0.9)),
        ((B,), pytest.approx(0.6)),
        ((C,), pytest.approx(0.5)),
    ]  # a weaker duplicate of A does not use up the budget


def test_budget_is_per_kind():
    emphasize = [rec(Kind.EMPHASIZE, k) for k in (A, B, C)]
    ease = [rec(Kind.EASE, k) for k in (D, E, F)]
    out = _valid(*emphasize, *ease)
    assert len(out.of_kind(Kind.EMPHASIZE)) == 3
    assert len(out.of_kind(Kind.EASE)) == 3


def test_contrast_needs_three_events_in_two_sessions():
    assert _valid(rec(Kind.CONTRAST, A, B, events=3, event_sessions=2)).recommendations
    assert not _valid(rec(Kind.CONTRAST, A, B, events=2, event_sessions=2)).recommendations
    assert not _valid(rec(Kind.CONTRAST, A, B, events=9, event_sessions=1)).recommendations
    unknown = rec(Kind.CONTRAST, A, B, events=9)
    unknown = replace(unknown, evidence=replace(unknown.evidence, event_sessions=None))
    assert not _valid(unknown).recommendations  # unknown sessions count as none


def test_the_contrast_floor_does_not_apply_to_other_kinds():
    assert _valid(rec(Kind.FOCUS, A, events=2)).recommendations
    assert _valid(rec(Kind.FOCUS_PAIR, A, B, events=2)).recommendations
    assert _valid(rec(Kind.EMPHASIZE, A, events=2)).recommendations


def test_at_most_five_recommendations_per_kind():
    recs = [rec(Kind.CONTRAST, A, k) for k in (B, C, D, E, F, G)]
    assert len(_valid(*recs).recommendations) == MAX_PER_KIND


def test_summary_is_trimmed():
    out = validate_advice(LessonAdvice(summary="  " + "x" * 500), COURSE)
    assert len(out.summary) == MAX_SUMMARY_CHARS


def test_the_core_writes_the_summary_when_the_advisor_wrote_none():
    out = _valid(rec(Kind.FOCUS, A, events=4, opportunities=40))
    assert out.summary == "a needs the most work: 4 errors in 40 presses."


def test_the_advisor_s_own_summary_stays():
    out = validate_advice(advice(rec(Kind.FOCUS, A), summary=" Mine. "), COURSE)
    assert out.summary == "Mine."


def test_the_summary_is_rendered_from_the_validated_recommendations():
    out = _valid(rec(Kind.FOCUS, Z, events=9), rec(Kind.EASE, A))  # Z is locked
    assert out.summary == ON_TRACK


def test_failed_advice_gets_no_rendered_summary():
    out = validate_advice(LessonAdvice(error="boom"), COURSE)
    assert out.summary == ""


# --- summary ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("recommendation", "text"),
    [
        (
            rec(Kind.CONTRAST, A, F, events=9, opportunities=90),
            "You typed f instead of a 9 times in 90 presses — practice a and f.",
        ),
        (
            rec(Kind.FOCUS, B, events=3, opportunities=40),
            "b needs the most work: 3 errors in 40 presses.",
        ),
        (
            rec(Kind.FOCUS_PAIR, A, B, events=4, opportunities=30),
            "ab needs the most work: 4 errors in 30 presses.",
        ),
        (
            rec(Kind.EMPHASIZE, C, reason=Reason.SPEED),
            "c is slower than your goal — it gets extra practice.",
        ),
        (
            rec(Kind.EMPHASIZE, C, reason=Reason.ACCURACY),
            "c has more errors than the others — it gets extra practice.",
        ),
    ],
)
def test_summary_templates(recommendation, text):
    assert render_summary(advice(recommendation)) == text


def test_the_strongest_recommendation_with_three_events_leads():
    out = render_summary(
        advice(
            rec(Kind.FOCUS, A, events=2, applied=0.9),  # two events never lead
            rec(Kind.EMPHASIZE, B, reason=Reason.SPEED, applied=0.5),
            rec(Kind.EMPHASIZE, C, reason=Reason.SPEED, applied=0.7),
            rec(Kind.EASE, D, events=40, applied=1.0),  # EASE never leads
        )
    )
    assert out == "c is slower than your goal — it gets extra practice."


def test_on_track_when_only_ease_or_nothing():
    assert render_summary(advice()) == ON_TRACK
    assert render_summary(advice(rec(Kind.EASE, A))) == ON_TRACK


def test_no_summary_when_the_evidence_is_weak():
    assert render_summary(advice(rec(Kind.FOCUS, A, events=2), rec(Kind.EASE, B))) == ""


def test_summary_writes_unprintable_keys_as_codes():
    out = render_summary(advice(rec(Kind.EMPHASIZE, 0x07, reason=Reason.SPEED)))
    assert out.startswith("U+0007 is slower")


def test_failed_advice_loses_its_recommendations_but_keeps_the_error():
    failed = LessonAdvice(source="llm", error="boom", recommendations=(rec(Kind.FOCUS, A),))
    out = validate_advice(failed, COURSE)
    assert out.failed
    assert (out.source, out.error) == ("llm", "boom")
    assert not out.actionable


def test_with_no_course_nothing_survives():
    empty = CourseState(unlocked=(), target_cpm=0, confidence={})
    assert not validate_advice(advice(rec(Kind.FOCUS, A)), empty).actionable


# --- focus --------------------------------------------------------------------


def test_focus_may_move_only_inside_the_choices():
    stage1 = FocusChoices(keys=frozenset({A, B}), pairs=frozenset())
    assert apply_focus_advice(C, None, advice(rec(Kind.FOCUS, B)), stage1) == (B, None)
    assert apply_focus_advice(C, None, advice(rec(Kind.FOCUS, D)), stage1) is None
    assert apply_focus_advice(C, None, advice(rec(Kind.FOCUS_PAIR, A, B)), stage1) is None


def test_gate_stage_allows_only_the_gate_pairs():
    gate = Bigram(C, A)
    stage2 = FocusChoices(keys=frozenset(), pairs=frozenset({gate}))
    assert apply_focus_advice(B, None, advice(rec(Kind.FOCUS_PAIR, C, A)), stage2) == (A, gate)
    assert apply_focus_advice(A, None, advice(rec(Kind.FOCUS_PAIR, A, B)), stage2) is None
    assert apply_focus_advice(A, None, advice(rec(Kind.FOCUS, B)), stage2) is None


def test_late_stage_allows_any_pair_of_unlocked_keys():
    late = FocusChoices(keys=frozenset({A, B, C}), pairs=None)
    got = apply_focus_advice(A, None, advice(rec(Kind.FOCUS_PAIR, B, C)), late)
    assert got == (C, Bigram(B, C))
    assert apply_focus_advice(A, None, advice(rec(Kind.FOCUS_PAIR, B, Z)), late) is None


def test_advice_that_repeats_the_engine_choice_changes_nothing():
    late = FocusChoices(keys=frozenset({A, B}), pairs=None)
    assert apply_focus_advice(A, None, advice(rec(Kind.FOCUS, A)), late) is None


def test_the_strongest_allowed_focus_wins_and_pairs_come_first():
    late = FocusChoices(keys=frozenset({A, B, C}), pairs=None)
    keys = advice(rec(Kind.FOCUS, A, strength=0.3), rec(Kind.FOCUS, B, strength=0.9))
    assert apply_focus_advice(C, None, keys, late) == (B, None)
    both = advice(rec(Kind.FOCUS, B), rec(Kind.FOCUS_PAIR, A, C, strength=0.1))
    assert apply_focus_advice(B, None, both, late) == (C, Bigram(A, C))


# --- weights ------------------------------------------------------------------


def test_weights_scale_with_the_effective_strength_and_do_not_mutate():
    weights = {"a": 1.0, "b": 1.0, "c": 1.0}
    out = weigh_advice(
        weights,
        advice(rec(Kind.EMPHASIZE, A, strength=1.0), rec(Kind.EASE, B, strength=0.5)),
    )
    assert out["a"] == pytest.approx(1.0 + EMPHASIS_RANGE)
    assert out["b"] == pytest.approx(1.0 - EASE_RANGE * 0.5)
    assert out["c"] == 1.0
    assert weights == {"a": 1.0, "b": 1.0, "c": 1.0}


def test_weak_evidence_gives_a_smaller_push():
    weak = weigh_advice({"a": 1.0}, advice(rec(Kind.EMPHASIZE, A, events=2)))
    strong = weigh_advice({"a": 1.0}, advice(rec(Kind.EMPHASIZE, A, events=5)))
    assert 1.0 < weak["a"] < strong["a"]


def test_a_key_in_several_recommendations_takes_the_largest_change():
    out = weigh_advice(
        {"a": 1.0},
        advice(rec(Kind.EMPHASIZE, A, strength=0.2), rec(Kind.EMPHASIZE, A, strength=0.8)),
    )
    assert out["a"] == pytest.approx(1.0 + EMPHASIS_RANGE * 0.8)


def test_protected_keys_are_never_eased_and_unknown_keys_are_ignored():
    out = weigh_advice(
        {"a": 1.0, "b": 1.0},
        advice(rec(Kind.EASE, A, B), rec(Kind.EMPHASIZE, Z)),
        protected=frozenset({B}),
    )
    assert out["a"] < 1.0
    assert out["b"] == 1.0
    assert set(out) == {"a", "b"}


def test_protected_keys_may_still_be_emphasized():
    out = weigh_advice({"a": 1.0}, advice(rec(Kind.EMPHASIZE, A)), protected=frozenset({A}))
    assert out["a"] > 1.0


# --- word boosts --------------------------------------------------------------


def test_contrast_becomes_a_word_boost_for_both_keys():
    boosts = word_boosts(advice(rec(Kind.CONTRAST, E, A, strength=1.0)), word_count=20)
    assert len(boosts) == 1
    boost = boosts[0]
    assert boost.needs_all == frozenset("ea")
    assert boost.factor == pytest.approx(2.0)
    assert boost.min_words == 4  # 1.0 * 20 / 5, and at most 20% of the lesson
    assert boost.matches("tea")
    assert not boost.matches("tee")


def test_weak_contrast_reserves_fewer_words_and_other_kinds_make_no_boost():
    weak = word_boosts(advice(rec(Kind.CONTRAST, E, A, events=2)), word_count=20)
    assert weak[0].min_words == 2
    assert word_boosts(advice(rec(Kind.EMPHASIZE, E)), word_count=20) == ()


def test_reserved_words_are_capped_at_a_fifth_of_the_lesson():
    boost = word_boosts(advice(rec(Kind.CONTRAST, E, A)), word_count=5)[0]
    assert boost.min_words == 1


# --- helpers ------------------------------------------------------------------


def test_error_rate_ranking_shrinks_rare_keys():
    rare = KeyTally(samples=1, time_ns=1, errors=1, attempts=2)
    often = KeyTally(samples=50, time_ns=50, errors=20, attempts=60)
    assert [cp for cp, _ in error_rate_ranked({A: rare, B: often})] == [B, A]


@pytest.mark.parametrize(("cp", "text"), [(A, "a"), (ord(" "), "U+0020"), (0x07, "U+0007")])
def test_format_char(cp: int, text: str):
    assert format_char(cp) == text


def _pos(cp: int, row: int, col: int, hand: Hand = Hand.L, *, shifted: bool = False) -> KeyPos:
    return KeyPos(cp, row, col, Finger.INDEX, hand, shifted)


def test_neighbors_are_adjacent_keys_of_the_same_hand():
    keys = {
        A: _pos(A, 1, 1),
        B: _pos(B, 1, 2),
        C: _pos(C, 0, 2),  # diagonal
        D: _pos(D, 1, 3),  # two columns away
        E: _pos(E, 1, 2, Hand.R),  # other hand
        F: _pos(F, 1, 1, shifted=True),
    }
    assert neighbors(keys, A) == (B, C)
    assert neighbors(keys, Z) == ()


# --- recency -------------------------------------------------------------------


def test_session_weights_fall_by_the_decay_each_session():
    assert session_weights(4, 0.5) == (1.0, 0.5, 0.25, 0.125)
    assert session_weights(3, 1.0) == (1.0, 1.0, 1.0)
    assert session_weights(0, 0.85) == ()


def test_recent_tally_has_a_mean_time_and_an_error_rate():
    t = RecentTally(samples=4.0, time_ns=4 * 200e6, errors=1.0, attempts=5.0)
    assert t.mean_ms == pytest.approx(200.0)
    assert t.error_rate == pytest.approx(0.2)
    assert RecentTally(0.0, 0.0, 0.0, 0.0).mean_ms == 0.0
    assert RecentTally(0.0, 0.0, 0.0, 0.0).error_rate == 0.0


def test_error_rate_ranking_accepts_recent_tallies():
    worse = RecentTally(samples=5.0, time_ns=5.0, errors=4.0, attempts=9.0)
    better = RecentTally(samples=50.0, time_ns=50.0, errors=1.0, attempts=51.0)
    assert [cp for cp, _ in error_rate_ranked({A: better, B: worse})] == [B, A]


def test_the_default_decay_is_below_one_so_recent_sessions_weigh_more():
    assert 0.0 < DEFAULT_RECENCY_DECAY < 1.0
    assert AdvisorConfig().recency_decay == DEFAULT_RECENCY_DECAY
