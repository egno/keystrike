"""CLI-only use cases for git-backed settings/session sync."""

from __future__ import annotations

from dataclasses import dataclass

from keystrike.domain.models import SyncStatusReport
from keystrike.domain.protocols import StatsRebuilder, SyncGateway


@dataclass(slots=True)
class InitSync:
    gateway: SyncGateway

    def __call__(self, remote_url: str) -> None:
        self.gateway.init(remote_url)


@dataclass(slots=True)
class PullSync:
    gateway: SyncGateway
    rebuild: StatsRebuilder

    def __call__(self) -> int:
        return self.gateway.pull(self.rebuild)


@dataclass(slots=True)
class PushSync:
    gateway: SyncGateway

    def __call__(self) -> bool:
        return self.gateway.push()


@dataclass(slots=True)
class GetSyncStatus:
    gateway: SyncGateway

    def __call__(self) -> SyncStatusReport:
        return self.gateway.status()
