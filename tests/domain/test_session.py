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
