from keystrike.infrastructure.bundled_layouts.colemak_dh import LAYOUT as COLEMAK_DH
from keystrike.infrastructure.bundled_layouts.qwerty import LAYOUT as QWERTY
from keystrike.presentation.widgets.kb_heatmap import render_heatmap


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
    a_span_high = next(s for s in high.spans if high.plain[s.start:s.end].strip() == "a")
    a_span_low = next(s for s in low.spans if low.plain[s.start:s.end].strip() == "a")
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


def test_focus_key_style_overrides_confidence():
    text = render_heatmap(QWERTY, {ord("a"): 1.5}, focus=ord("a"))
    span = next(s for s in text.spans if text.plain[s.start : s.end].strip() == "a")
    assert span.style == "bold underline cyan"


def test_focus_key_style_applies_even_without_heatmap_entry():
    # A locked/never-practiced key can still be the focus (e.g. freshly unlocked).
    text = render_heatmap(QWERTY, {}, focus=ord("a"))
    span = next(s for s in text.spans if text.plain[s.start : s.end].strip() == "a")
    assert span.style == "bold underline cyan"
