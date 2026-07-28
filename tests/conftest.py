from __future__ import annotations

import random

import pytest

from tests.fakes import FakeClock, FakeIdGenerator, FakeSessionRepository


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
