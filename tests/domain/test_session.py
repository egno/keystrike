from keystrike.domain.enums import Mode
from keystrike.domain.session import Session, skip_leading_whitespace


def _session(target_text: str) -> Session:
    return Session(
        id="s1",
        target_text=target_text,
        layout="qwerty",
        mode=Mode.ADAPTIVE,
        lang="en",
        started_at_wall=0.0,
        started_at_ns=0,
    )


def test_skip_leading_whitespace_empty_target():
    assert skip_leading_whitespace(_session(""), " ") is False


def test_skip_leading_whitespace_newline_enter_variants():
    session = _session("\nabc")
    assert skip_leading_whitespace(session, "\r") is False
    assert skip_leading_whitespace(session, "\n") is False
    assert skip_leading_whitespace(session, " ") is True


def test_skip_leading_whitespace_repeated_after_required_leading_char():
    session = _session(" ab")
    session.position = 1
    assert skip_leading_whitespace(session, " ") is True

    session = _session("\nabc")
    session.position = 1
    assert skip_leading_whitespace(session, "\n") is True
    assert skip_leading_whitespace(session, "\r") is True


def test_skip_leading_whitespace_at_word_start():
    session = _session("hi there")
    session.position = 3  # after "hi ", before 't'
    assert skip_leading_whitespace(session, " ") is True
    assert skip_leading_whitespace(session, "\t") is True


def test_skip_leading_whitespace_not_mid_word():
    session = _session("a b")
    session.position = 1  # target space between words
    assert skip_leading_whitespace(session, "\t") is False
