from keystrike.domain.confidence import FocusReason
from keystrike.domain.enums import FocusKind
from keystrike.domain.models import Bigram
from keystrike.infrastructure.bundled_layouts.colemak_dh import LAYOUT as COLEMAK_DH
from keystrike.infrastructure.bundled_layouts.qwerty import LAYOUT as QWERTY
from keystrike.presentation.widgets.kb_heatmap import (
    focus_transition_pair,
    format_focus_note,
    render_heatmap,
)


def test_render_heatmap_includes_every_alpha_key_once():
    text = render_heatmap(QWERTY, {})
    plain = text.plain
    for ch in "asdfghjkl":
        assert plain.count(ch) == 1


def test_render_heatmap_excludes_space_row():
    text = render_heatmap(QWERTY, {})
    assert text.plain.count("\n") == 3


def test_render_heatmap_colors_by_confidence():
    high = render_heatmap(QWERTY, {ord("a"): 1.5})
    low = render_heatmap(QWERTY, {ord("a"): 0.1})
    a_span_high = next(s for s in high.spans if high.plain[s.start : s.end].strip() == "a")
    a_span_low = next(s for s in low.spans if low.plain[s.start : s.end].strip() == "a")
    assert a_span_high.style != a_span_low.style


def test_staggered_layout_indents_each_row():
    # Base cell padding is 1 leading space; staggered rows add 2 more per row.
    lines = render_heatmap(QWERTY, {}).plain.splitlines()
    leading_spaces = [len(line) - len(line.lstrip(" ")) for line in lines]
    assert leading_spaces == [1, 3, 5]


def test_ortholinear_layout_has_no_row_indent():
    # Columns line up: only the base cell padding, no extra per-row offset.
    lines = render_heatmap(COLEMAK_DH, {}).plain.splitlines()
    leading_spaces = [len(line) - len(line.lstrip(" ")) for line in lines]
    assert leading_spaces == [1, 1, 1]


def test_focus_mastered_key_keeps_green_with_cyan_underline():
    text = render_heatmap(QWERTY, {ord("a"): 1.5}, focus=ord("a"))
    span = next(s for s in text.spans if text.plain[s.start : s.end].strip() == "a")
    style = str(span.style)
    assert "green" in style
    assert "cyan" in style


def test_focus_weak_key_keeps_confidence_color():
    text = render_heatmap(QWERTY, {ord("a"): 0.89}, focus=ord("a"))
    span = next(s for s in text.spans if text.plain[s.start : s.end].strip() == "a")
    style = str(span.style)
    assert "yellow" in style
    assert "underline" in style
    assert "cyan" not in style


def test_focus_key_style_applies_even_without_heatmap_entry():
    # A locked/never-practiced key can still be the focus (e.g. freshly unlocked).
    text = render_heatmap(QWERTY, {}, focus=ord("a"))
    span = next(s for s in text.spans if text.plain[s.start : s.end].strip() == "a")
    style = str(span.style)
    assert "grey37" in style
    assert "underline" in style
    assert "cyan" not in style


def test_render_heatmap_marks_due_for_review_with_magenta_underline():
    text = render_heatmap(QWERTY, {ord("a"): 1.5}, urgency={ord("a"): 0.5})
    span = next(s for s in text.spans if text.plain[s.start : s.end].strip() == "a")
    style = str(span.style)
    assert "magenta" in style
    assert "green" in style


def test_render_heatmap_weak_key_without_urgency_stays_red_only():
    text = render_heatmap(QWERTY, {ord("a"): 0.1}, urgency={ord("a"): 0.0})
    span = next(s for s in text.spans if text.plain[s.start : s.end].strip() == "a")
    style = str(span.style)
    assert "magenta" not in style
    assert "red" in style


def test_render_heatmap_focus_style_layers_on_review_underline():
    text = render_heatmap(
        QWERTY,
        {ord("a"): 1.5},
        focus=ord("a"),
        urgency={ord("a"): 1.0},
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
    assert "speed 0.95" in note
    assert "accuracy 92.0%" in note
    assert "0.89" in note
    assert "1.00" in note
    assert "weak" in note


def test_format_focus_note_review_includes_confidence_numbers():
    reason = FocusReason(kind=FocusKind.KEY_REVIEW)
    note = format_focus_note(ord("e"), reason, confidence=1.12, speed=1.15, accuracy=0.98)
    assert note is not None
    assert "speed 1.15" in note
    assert "accuracy 98.0%" in note
    assert "1.12" in note
    assert "1.00" in note


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
    assert "at" in note
    assert "speed 0.50" in note
    assert "accuracy 80.0%" in note
    assert "0.45" in note


def test_format_focus_note_none_without_reason():
    assert format_focus_note(ord("a"), None, confidence=0.5) is None


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
        QWERTY,
        {ord("e"): 0.89, ord("o"): 0.89},
        focus=ord("o"),
        focus_transition=(ord("e"), ord("o")),
    )
    for ch in "eo":
        span = next(s for s in text.spans if text.plain[s.start : s.end].strip() == ch)
        assert "underline" in str(span.style)
