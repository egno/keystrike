from random import Random

import pytest

from keystrike.domain.code_lesson import select_snippet


def test_select_snippet_raises_on_empty_sequence():
    with pytest.raises(ValueError, match="no snippets"):
        select_snippet([], "x", Random(0))


def test_select_snippet_returns_one_of_the_inputs():
    snippets = ["abc", "def", "ghi"]
    result = select_snippet(snippets, "x", Random(0))
    assert result in snippets


def test_select_snippet_prefers_snippets_containing_focus_char():
    snippets = ["no matches here at all", "xxxxxxxxxx"]
    rng = Random(1)
    picks = [select_snippet(snippets, "x", rng) for _ in range(50)]
    assert picks.count("xxxxxxxxxx") > picks.count("no matches here at all")
