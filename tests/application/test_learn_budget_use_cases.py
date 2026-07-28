import datetime as dt

from keystrike.application.learn_budget_use_cases import GetDailyLearnBudget
from keystrike.domain.enums import Mode
from keystrike.domain.models import SessionResult, Settings
from tests.fakes import FakeClock, FakeSessionRepository, FakeSettingsRepository

_TZ = dt.timezone(dt.timedelta(hours=3))


def _adaptive_header(duration_ns: int) -> SessionResult:
    return SessionResult(
        schema_version=1,
        session_id="s1",
        started_at=dt.datetime(2026, 7, 28, 10, 0, tzinfo=_TZ).timestamp(),
        duration_ns=duration_ns,
        layout="qwerty",
        mode=Mode.ADAPTIVE,
        lesson_alphabet=(),
        focus_key=ord("e"),
        total_keystrokes=1,
        correct_keystrokes=1,
    )


def test_get_daily_learn_budget_reads_completed_sessions():
    clock = FakeClock(wall=dt.datetime(2026, 7, 28, 18, 0, tzinfo=_TZ).timestamp())
    repo = FakeSessionRepository(headers=[_adaptive_header(5 * 60 * 1_000_000_000)])
    settings_repo = FakeSettingsRepository(Settings(learn_daily_minutes=10))

    budget = GetDailyLearnBudget(clock=clock, repo=repo, settings_repo=settings_repo, tz=_TZ)()

    assert budget.limited
    assert budget.remaining_ns == 5 * 60 * 1_000_000_000
    assert not budget.limit_reached


def test_get_daily_learn_budget_includes_extra_ns_for_active_session():
    clock = FakeClock(wall=dt.datetime(2026, 7, 28, 18, 0, tzinfo=_TZ).timestamp())
    repo = FakeSessionRepository(headers=[_adaptive_header(9 * 60 * 1_000_000_000)])
    settings_repo = FakeSettingsRepository(Settings(learn_daily_minutes=10))

    budget = GetDailyLearnBudget(
        clock=clock, repo=repo, settings_repo=settings_repo, tz=_TZ,
    )(extra_ns=2 * 60 * 1_000_000_000)

    assert budget.limit_reached
