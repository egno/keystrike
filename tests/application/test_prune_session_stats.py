from dataclasses import replace

from keystrike.application.stats_use_cases import PruneSessionStats
from keystrike.domain.enums import Mode
from keystrike.domain.models import KeyTally, SessionResult, SessionStats, Settings
from keystrike.domain.retention import stats_retention_count
from tests.fakes import FakeSessionRepository, FakeSettingsRepository


def _header(session_id: str, started_at: float) -> SessionResult:
    return SessionResult(
        schema_version=5,
        session_id=session_id,
        started_at=started_at,
        duration_ns=1_000_000_000,
        layout="qwerty",
        mode=Mode.ADAPTIVE,
        lesson_alphabet=(ord("a"),),
        focus_key=None,
        total_keystrokes=1,
        correct_keystrokes=1,
        stats=SessionStats(keys={ord("a"): KeyTally(1, 100_000_000, 0, 1)}),
    )


def test_prune_uses_settings_window_and_rewrites_only_when_needed():
    settings_repo = FakeSettingsRepository(Settings(confidence_session_window=2))
    keep = stats_retention_count(2)
    repo = FakeSessionRepository()
    for i in range(keep + 2):
        repo.save_header(_header(f"s{i}", started_at=float(i)))
    original = list(repo.headers)

    prune = PruneSessionStats(repo=repo, settings_repo=settings_repo)

    assert prune() == 2
    assert [h.stats.is_empty for h in repo.headers] == [True, True] + [False] * keep
    assert repo.headers[0] == replace(original[0], stats=SessionStats())

    rewritten = list(repo.headers)
    assert prune() == 0
    assert repo.headers == rewritten
