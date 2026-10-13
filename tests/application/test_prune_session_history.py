import datetime as dt
from dataclasses import replace

from keystrike.application.stats_use_cases import KeptSessionIds, PruneSessionHistory
from keystrike.domain.enums import Mode
from keystrike.domain.models import KeyTally, SessionResult, SessionStats, Settings
from keystrike.domain.retention import HISTORY_MIN_SESSIONS, stats_retention_count
from tests.fakes import FakeClock, FakeSessionRepository, FakeSettingsRepository


def _header(session_id: str, started_at: float, layout: str = "qwerty") -> SessionResult:
    return SessionResult(
        schema_version=5,
        session_id=session_id,
        started_at=started_at,
        duration_ns=1_000_000_000,
        layout=layout,
        mode=Mode.ADAPTIVE,
        lesson_alphabet=(ord("a"),),
        focus_key=None,
        total_keystrokes=1,
        correct_keystrokes=1,
        stats=SessionStats(keys={ord("a"): KeyTally(1, 100_000_000, 0, 1)}),
    )


def test_prune_drops_stats_by_settings_window_and_rewrites_only_when_needed():
    settings_repo = FakeSettingsRepository(Settings(confidence_session_window=2))
    keep = stats_retention_count(2)
    repo = FakeSessionRepository()
    for i in range(keep + 2):
        repo.save_header(_header(f"s{i}", started_at=float(i)))
    original = list(repo.headers)

    prune = PruneSessionHistory(repo=repo, settings_repo=settings_repo, clock=FakeClock())

    assert prune() == 2
    assert [h.stats.is_empty for h in repo.headers] == [True, True] + [False] * keep
    assert repo.headers[0] == replace(original[0], stats=SessionStats())

    rewritten = list(repo.headers)
    assert prune() == 0
    assert repo.headers == rewritten


# FakeClock's wall time is 2023-11-14 22:13 UTC.
_DAY_BEFORE = 1_700_000_000.0 - 86_400


def test_prune_deletes_rows_outside_history_but_keeps_today():
    settings_repo = FakeSettingsRepository(Settings(confidence_session_window=2))
    clock = FakeClock()
    repo = FakeSessionRepository()
    for i in range(HISTORY_MIN_SESSIONS + 3):
        repo.save_header(_header(f"old{i}", started_at=_DAY_BEFORE + i))
    for i in range(HISTORY_MIN_SESSIONS + 1):
        repo.save_header(_header(f"today{i}", started_at=clock.wall - 1000 + i))

    PruneSessionHistory(repo=repo, settings_repo=settings_repo, clock=clock)()

    assert [h.session_id for h in repo.headers] == [
        f"today{i}" for i in range(HISTORY_MIN_SESSIONS + 1)
    ]


def test_kept_ids_use_clock_day_and_time_zone():
    clock = FakeClock(tz=dt.timezone(dt.timedelta(hours=-12)))
    settings_repo = FakeSettingsRepository(Settings(confidence_session_window=1))
    # 01:13 UTC on the clock's UTC day, but the day before at UTC-12.
    early = _header("early", started_at=clock.wall - 21 * 3600)
    rows = [early] + [_header(f"n{i}", clock.wall + i) for i in range(HISTORY_MIN_SESSIONS)]

    assert "early" not in KeptSessionIds(clock=clock, settings_repo=settings_repo)(rows)
    assert "early" in KeptSessionIds(clock=FakeClock(), settings_repo=settings_repo)(rows)
