from __future__ import annotations

import random

import pytest

from tests.fakes import FakeClock, FakeIdGenerator, FakeSessionRepository


@pytest.fixture(autouse=True)
def _snapshot_no_color(  # pyright: ignore[reportUnusedFunction]
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Match CI snapshot job: baselines assume NO_COLOR=1 (grey, not theme accent)."""
    if request.node.get_closest_marker("snapshot") is not None:
        monkeypatch.setenv("NO_COLOR", "1")


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def id_gen() -> FakeIdGenerator:
    return FakeIdGenerator()


@pytest.fixture
def session_repo() -> FakeSessionRepository:
    return FakeSessionRepository()


@pytest.fixture
def rng() -> random.Random:
    return random.Random(42)
