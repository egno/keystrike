from dataclasses import dataclass, field

from keystrike.application.sync_use_cases import GetSyncStatus, InitSync, PullSync, PushSync
from keystrike.domain.models import SyncStatusReport
from tests.fakes import FakeSyncStore


@dataclass(slots=True)
class _RecordingRebuild:
    """Records each layout it's called with — a StatsRebuilder test double."""

    calls: list[str] = field(default_factory=list)

    def __call__(self, layout: str) -> None:
        self.calls.append(layout)


def test_init_sync_configures_gateway_with_remote_url():
    gateway = FakeSyncStore()
    init = InitSync(gateway=gateway)

    init("https://example.com/repo.git")

    assert gateway.configured is True
    assert gateway.remote_url == "https://example.com/repo.git"
    assert gateway.init_calls == ["https://example.com/repo.git"]


def test_pull_sync_returns_gateway_result():
    gateway = FakeSyncStore(pull_result=3)
    rebuild = _RecordingRebuild()
    pull = PullSync(gateway=gateway, rebuild=rebuild)

    result = pull()

    assert result == 3


def test_pull_sync_rebuilds_aggregates_for_pulled_layouts():
    gateway = FakeSyncStore(pulled_layouts=["qwerty", "dvorak"], pull_result=2)
    rebuild = _RecordingRebuild()
    pull = PullSync(gateway=gateway, rebuild=rebuild)

    result = pull()

    assert result == 2
    assert rebuild.calls == ["qwerty", "dvorak"]
    assert gateway.rebuilt_layouts == ["qwerty", "dvorak"]


def test_push_sync_returns_gateway_result():
    gateway = FakeSyncStore(push_result=True)
    push = PushSync(gateway=gateway)

    assert push() is True


def test_push_sync_returns_false_when_gateway_reports_no_push():
    gateway = FakeSyncStore(push_result=False)
    push = PushSync(gateway=gateway)

    assert push() is False


def test_get_sync_status_returns_gateway_report():
    report = SyncStatusReport(
        configured=True,
        remote_url="https://example.com/repo.git",
        git_status="dirty",
        local_sessions=5,
        clone_sessions=3,
        only_local=2,
        only_clone=1,
    )
    gateway = FakeSyncStore(configured=True, status_report=report)
    get_status = GetSyncStatus(gateway=gateway)

    assert get_status() is report


def test_get_sync_status_default_when_unconfigured():
    gateway = FakeSyncStore()
    get_status = GetSyncStatus(gateway=gateway)

    status = get_status()

    assert status.configured is False
    assert status.remote_url is None
