from keystrike.domain.enums import Mode
from keystrike.domain.models import Keystroke, SessionResult
from keystrike.domain.null_adapters import (
    NULL_AGGREGATES_ENSURER,
    NULL_DAILY_LEARN_BUDGET,
    NULL_STATS_REBUILDER,
    NullSessionRepository,
)


def test_null_session_repository_is_inert():
    repo = NullSessionRepository()
    k = Keystroke(codepoint=ord("a"), typed=ord("a"), t_ns=0, correct=True)
    repo.append_keystroke("s1", 0.0, k)  # must not raise

    header = SessionResult(
        schema_version=1,
        session_id="s1",
        started_at=0.0,
        duration_ns=0,
        layout="qwerty",
        mode=Mode.ADAPTIVE,
        lesson_alphabet=(),
        focus_key=None,
        total_keystrokes=0,
        correct_keystrokes=0,
    )
    repo.save_header(header)  # must not raise

    assert list(repo.iter_headers("qwerty")) == []
    assert list(repo.load_keystrokes("s1")) == []


def test_null_stats_rebuilder_returns_none():
    assert NULL_STATS_REBUILDER("qwerty") is None


def test_null_aggregates_ensurer_returns_empty_dict():
    assert NULL_AGGREGATES_ENSURER("qwerty") == {}


def test_null_daily_learn_budget_is_unlimited():
    budget = NULL_DAILY_LEARN_BUDGET()
    assert not budget.limited
    assert not budget.limit_reached
