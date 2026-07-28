import datetime as dt

from keystrike.domain.daily_learn import (
    compute_daily_learn_budget,
    daily_learn_duration_ns,
    format_daily_learn_display,
    session_local_date,
)
from keystrike.domain.enums import Mode
from keystrike.domain.models import SessionResult

_TZ = dt.timezone(dt.timedelta(hours=3))
_DAY = dt.date(2026, 7, 28)


def _header(*, mode: Mode = Mode.ADAPTIVE, started_at: float, duration_ns: int) -> SessionResult:
    return SessionResult(
        schema_version=1,
        session_id=f"s-{started_at}",
        started_at=started_at,
        duration_ns=duration_ns,
        layout="qwerty",
        mode=mode,
        lesson_alphabet=(),
        focus_key=ord("e"),
        total_keystrokes=10,
        correct_keystrokes=10,
    )


def test_session_local_date_uses_timezone():
    # 2026-07-27 23:30 UTC = 2026-07-28 02:30 in UTC+3
    ts = dt.datetime(2026, 7, 27, 23, 30, tzinfo=dt.UTC).timestamp()
    assert session_local_date(ts, _TZ) == _DAY


def test_daily_learn_duration_sums_adaptive_sessions_on_day_only():
    noon = dt.datetime(2026, 7, 28, 12, 0, tzinfo=_TZ).timestamp()
    yesterday = dt.datetime(2026, 7, 27, 12, 0, tzinfo=_TZ).timestamp()
    headers = [
        _header(started_at=noon, duration_ns=60_000_000_000),
        _header(started_at=yesterday, duration_ns=120_000_000_000),
        _header(started_at=noon + 60, duration_ns=30_000_000_000),
    ]
    assert daily_learn_duration_ns(headers, _DAY, tz=_TZ) == 90_000_000_000


def test_compute_daily_learn_budget_unlimited_when_limit_zero():
    budget = compute_daily_learn_budget(completed_ns=999_000_000_000, limit_minutes=0)
    assert not budget.limited
    assert not budget.limit_reached


def test_format_daily_learn_display_shows_used_and_limit():
    budget = compute_daily_learn_budget(completed_ns=9 * 60 * 1_000_000_000, limit_minutes=10)
    text = format_daily_learn_display(budget, label="Learn today:")
    assert "9.0" in text
    assert "/10 min" in text
    assert "left" not in text


def test_format_daily_learn_display_limit_reached():
    budget = compute_daily_learn_budget(completed_ns=10 * 60 * 1_000_000_000, limit_minutes=10)
    text = format_daily_learn_display(budget, label="Learn today:")
    assert "Daily learn limit reached" in text


def test_compute_daily_learn_budget_tracks_remaining_and_limit_reached():
    budget = compute_daily_learn_budget(completed_ns=6 * 60 * 1_000_000_000, limit_minutes=10)
    assert budget.limited
    assert budget.remaining_ns == 4 * 60 * 1_000_000_000
    assert not budget.limit_reached

    over = compute_daily_learn_budget(
        completed_ns=9 * 60 * 1_000_000_000,
        limit_minutes=10,
        extra_ns=2 * 60 * 1_000_000_000,
    )
    assert over.limit_reached
    assert over.remaining_ns == 0
