from keystrike.domain.enums import FocusKind
from keystrike.domain.focus import FocusReason
from keystrike.domain.models import Bigram
from keystrike.infrastructure.bundled_layouts.colemak_dh import LAYOUT as COLEMAK_DH
from keystrike.infrastructure.bundled_layouts.qwerty import LAYOUT as QWERTY
from keystrike.presentation.widgets.kb_heatmap import (
    HeatmapDisplay,
    focus_reason_label,
    focus_reason_label_short,
    focus_transition_pair,
    format_focus_note,
    render_heatmap,
)


def test_render_heatmap_includes_every_alpha_key_once():
    text = render_heatmap(HeatmapDisplay(QWERTY, {}))
    plain = text.plain
    for ch in "asdfghjkl":
        assert plain.count(ch) == 1


def test_render_heatmap_excludes_space_row():
    text = render_heatmap(HeatmapDisplay(QWERTY, {}))
    assert text.plain.count("\n") == 3


def test_render_heatmap_colors_by_confidence():
    high = render_heatmap(HeatmapDisplay(QWERTY, {ord("a"): 1.5}))
    low = render_heatmap(HeatmapDisplay(QWERTY, {ord("a"): 0.1}))
    a_span_high = next(s for s in high.spans if high.plain[s.start : s.end].strip() == "a")
    a_span_low = next(s for s in low.spans if low.plain[s.start : s.end].strip() == "a")
    assert a_span_high.style != a_span_low.style


def test_staggered_layout_indents_each_row():
    # Base cell padding is 1 leading space; staggered rows add 2 more per row.
    lines = render_heatmap(HeatmapDisplay(QWERTY, {})).plain.splitlines()
    leading_spaces = [len(line) - len(line.lstrip(" ")) for line in lines]
    assert leading_spaces == [1, 3, 5]


def test_ortholinear_layout_has_no_row_indent():
    # Columns line up: only the base cell padding, no extra per-row offset.
    lines = render_heatmap(HeatmapDisplay(COLEMAK_DH, {})).plain.splitlines()
    leading_spaces = [len(line) - len(line.lstrip(" ")) for line in lines]
    assert leading_spaces == [1, 1, 1]


def test_focus_mastered_key_keeps_green_with_cyan_underline():
    text = render_heatmap(HeatmapDisplay(QWERTY, {ord("a"): 1.5}, focus=ord("a")))
    span = next(s for s in text.spans if text.plain[s.start : s.end].strip() == "a")
    style = str(span.style)
    assert "green" in style
    assert "cyan" in style


def test_focus_weak_key_keeps_confidence_color():
    text = render_heatmap(HeatmapDisplay(QWERTY, {ord("a"): 0.89}, focus=ord("a")))
    span = next(s for s in text.spans if text.plain[s.start : s.end].strip() == "a")
    style = str(span.style)
    assert "yellow" in style
    assert "underline" in style
    assert "cyan" not in style


def test_focus_key_style_applies_even_without_heatmap_entry():
    # A locked/never-practiced key can still be the focus (e.g. freshly unlocked).
    text = render_heatmap(HeatmapDisplay(QWERTY, {}, focus=ord("a")))
    span = next(s for s in text.spans if text.plain[s.start : s.end].strip() == "a")
    style = str(span.style)
    assert "grey37" in style
    assert "underline" in style
    assert "cyan" not in style


def test_render_heatmap_marks_due_for_review_with_magenta_underline():
    text = render_heatmap(HeatmapDisplay(QWERTY, {ord("a"): 1.5}, urgency={ord("a"): 0.5}))
    span = next(s for s in text.spans if text.plain[s.start : s.end].strip() == "a")
    style = str(span.style)
    assert "magenta" in style
    assert "green" in style


def test_render_heatmap_weak_key_without_urgency_stays_red_only():
    text = render_heatmap(HeatmapDisplay(QWERTY, {ord("a"): 0.1}, urgency={ord("a"): 0.0}))
    span = next(s for s in text.spans if text.plain[s.start : s.end].strip() == "a")
    style = str(span.style)
    assert "magenta" not in style
    assert "red" in style


def test_render_heatmap_focus_style_layers_on_review_underline():
    text = render_heatmap(
        HeatmapDisplay(
            QWERTY,
            {ord("a"): 1.5},
            focus=ord("a"),
            urgency={ord("a"): 1.0},
        )
    )
    span = next(s for s in text.spans if text.plain[s.start : s.end].strip() == "a")
    style = str(span.style)
    assert "green" in style
    assert "magenta" in style
    assert "cyan" in style


def test_format_focus_note_weak_includes_confidence_numbers():
    reason = FocusReason(kind=FocusKind.KEY_WEAK)
    note = format_focus_note(ord("a"), reason, confidence=0.89, speed=0.95, accuracy=0.92)
    assert note is not None
    assert "a · wk · 0.95 · 92% · 0.89" in note


def test_format_focus_note_review_includes_confidence_numbers():
    reason = FocusReason(kind=FocusKind.KEY_REVIEW)
    note = format_focus_note(ord("e"), reason, confidence=1.12, speed=1.15, accuracy=0.98)
    assert note is not None
    assert "e · rev · 1.15 · 98% · 1.12" in note


def test_format_focus_note_weak_transition():
    reason = FocusReason(kind=FocusKind.TRANSITION_WEAK, pair=Bigram(ord("a"), ord("t")))
    note = format_focus_note(
        ord("t"),
        reason,
        confidence=0.45,
        speed=0.50,
        accuracy=0.80,
    )
    assert note is not None
    assert "at · wk · 0.50 · 80% · 0.45" in note


def test_format_focus_note_none_without_reason():
    assert format_focus_note(ord("a"), None, confidence=0.5) is None


def test_format_focus_note_calibrating_includes_press_count():
    reason = FocusReason(kind=FocusKind.KEY_CALIBRATING)
    note = format_focus_note(
        ord("t"),
        reason,
        confidence=0.90,
        speed=1.59,
        accuracy=1.0,
        attempts=9,
        min_attempts=10,
    )
    assert note is not None
    assert "t · cal 9/10 · 1.59 · 100% · 0.90" in note
    assert "wk" not in note


def test_focus_reason_label_calibrating():
    assert focus_reason_label(FocusReason(kind=FocusKind.KEY_CALIBRATING)) == "calibrating"
    pair = FocusReason(
        kind=FocusKind.TRANSITION_CALIBRATING,
        pair=Bigram(ord("e"), ord("o")),
    )
    assert focus_reason_label(pair) == "eo calibrating transition"


def test_focus_reason_label_short():
    assert focus_reason_label_short(FocusReason(kind=FocusKind.KEY_WEAK)) == "wk"
    assert focus_reason_label_short(FocusReason(kind=FocusKind.KEY_CALIBRATING)) == "cal"
    assert focus_reason_label_short(FocusReason(kind=FocusKind.KEY_REVIEW)) == "rev"
    pair = FocusReason(
        kind=FocusKind.TRANSITION_WEAK,
        pair=Bigram(ord("e"), ord("o")),
    )
    assert focus_reason_label_short(pair) == "wk"


def test_render_heatmap_calibrating_key_shows_green_not_yellow():
    # Ramped confidence 0.9 would be yellow; skill 1.0 should be green.
    text = render_heatmap(HeatmapDisplay(QWERTY, {ord("t"): 1.0}, focus=ord("t")))
    span = next(s for s in text.spans if text.plain[s.start : s.end].strip() == "t")
    style = str(span.style)
    assert "green" in style
    assert "yellow" not in style
    assert "cyan" in style


def test_focus_transition_pair_returns_pair_for_transition_kinds():
    weak = FocusReason(kind=FocusKind.TRANSITION_WEAK, pair=Bigram(ord("e"), ord("o")))
    review = FocusReason(kind=FocusKind.TRANSITION_REVIEW, pair=Bigram(ord("a"), ord("t")))
    assert focus_transition_pair(weak) == (ord("e"), ord("o"))
    assert focus_transition_pair(review) == (ord("a"), ord("t"))
    assert focus_transition_pair(FocusReason(kind=FocusKind.KEY_WEAK)) is None
    assert focus_transition_pair(FocusReason(kind=FocusKind.KEY_REVIEW)) is None
    assert focus_transition_pair(None) is None


def test_render_heatmap_highlights_both_transition_keys():
    text = render_heatmap(
        HeatmapDisplay(
            QWERTY,
            {ord("e"): 0.89, ord("o"): 0.89},
            focus=ord("o"),
            focus_transition=(ord("e"), ord("o")),
        )
    )
    for ch in "eo":
        span = next(s for s in text.spans if text.plain[s.start : s.end].strip() == ch)
        assert "underline" in str(span.style)
