import tomllib

from keystrike.infrastructure.toml_escape import escape_toml_string


def test_escapes_backslash_and_quote():
    assert escape_toml_string('a\\b"c') == 'a\\\\b\\"c'


def test_escapes_newline_tab_and_carriage_return():
    """Regression: an unescaped control char breaks a hand-rolled TOML
    writer's line structure -- verified by round-tripping through tomllib."""
    raw = "line1\nline2\ttabbed\r\n"
    escaped = escape_toml_string(raw)
    loaded = tomllib.loads(f'value = "{escaped}"\n')
    assert loaded["value"] == raw


def test_escapes_other_control_characters_as_unicode_escape():
    raw = "a\x01b\x7fc"
    escaped = escape_toml_string(raw)
    loaded = tomllib.loads(f'value = "{escaped}"\n')
    assert loaded["value"] == raw


def test_plain_text_round_trips_unchanged():
    raw = "https://example.com/words.txt"
    assert escape_toml_string(raw) == raw
