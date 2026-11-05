from __future__ import annotations

import asyncio

import pytest

from keystrike.application.advisor_registry import AdvisorRegistry
from keystrike.application.advisor_use_cases import (
    AdvisorConfigError,
    OffDeviceConfirmationRequired,
    TestAdvisor,
    UpdateAdvisorConfig,
)
from keystrike.domain.advice import (
    AdvisorCapabilities,
    AdvisorConfig,
    AdvisorContext,
    AdvisorSpec,
    Kind,
    LessonAdvice,
    SettingField,
)
from tests.advice_helpers import rec
from tests.fakes import FakeAdvisorConfigRepository, FakeKeystrokeArchive

E = ord("e")


async def _good(_ctx: AdvisorContext) -> LessonAdvice:
    return LessonAdvice(
        summary="fine", recommendations=(rec(Kind.FOCUS, E), rec(Kind.EMPHASIZE, ord("z")))
    )


async def _slow(_ctx: AdvisorContext):
    await asyncio.sleep(10)


def _spec(name: str, *, keystrokes: bool, off_device: bool, advisor=_good) -> AdvisorSpec:
    def create(cfg):
        if cfg.get("endpoint") == "bad":
            raise ValueError("bad endpoint")
        return advisor

    return AdvisorSpec(
        name,
        name.upper(),
        AdvisorCapabilities(needs_keystrokes=keystrokes, sends_data_off_device=off_device),
        (SettingField("endpoint", "Endpoint", "http://x"),),
        create,
    )


def _setup(config: AdvisorConfig | None = None):
    registry = AdvisorRegistry()
    registry.register(_spec("local", keystrokes=False, off_device=False))
    registry.register(_spec("remote", keystrokes=True, off_device=True))
    repo = FakeAdvisorConfigRepository(config or AdvisorConfig(active="local"))
    archive = FakeKeystrokeArchive()
    archive.save("old", [])
    forgotten: list[bool] = []
    update = UpdateAdvisorConfig(
        repo=repo, registry=registry, archive=archive, forget_advice=lambda: forgotten.append(True)
    )
    return update, repo, archive, forgotten, registry


def test_saves_the_active_advisor_and_its_section():
    update, repo, _archive, _forgotten, _ = _setup()
    update("local", {"endpoint": " http://h "})
    assert repo.config.active == "local"
    assert repo.config.section("local") == {"endpoint": "http://h"}


def test_unknown_advisor_is_rejected():
    update, repo, *_ = _setup()
    with pytest.raises(AdvisorConfigError, match="Unknown"):
        update("ghost", {})
    assert repo.config.active == "local"


def test_bad_config_is_rejected_with_the_advisors_message():
    update, repo, *_ = _setup()
    with pytest.raises(AdvisorConfigError, match="bad endpoint"):
        update("local", {"endpoint": "bad"})
    assert repo.config == AdvisorConfig(active="local")


def test_off_device_advisor_needs_confirmation_once():
    update, repo, *_ = _setup()
    with pytest.raises(OffDeviceConfirmationRequired, match="sends practice data"):
        update("remote", {"endpoint": "http://h"})
    assert repo.config.active == "local"  # nothing saved
    update("remote", {"endpoint": "http://h"}, confirm_off_device=True)
    assert repo.config.confirmed_off_device == ("remote",)
    update("remote", {"endpoint": "http://h"})  # already confirmed: no prompt


def test_check_saves_nothing():
    update, repo, *_ = _setup()
    update.check("local", {"endpoint": "http://h"})
    assert repo.config == AdvisorConfig(active="local")
    with pytest.raises(OffDeviceConfirmationRequired):
        update.check("remote", {})


def test_an_advisor_without_keystrokes_deletes_the_archive():
    update, _repo, archive, *_ = _setup()
    update("local", {})
    assert archive.saved == {}


def test_an_advisor_that_needs_keystrokes_keeps_the_archive():
    update, _repo, archive, *_ = _setup(
        AdvisorConfig(active="remote", confirmed_off_device=("remote",))
    )
    update("remote", {})
    assert "old" in archive.saved


def test_off_forgets_the_kept_advice():
    update, repo, _archive, forgotten, _ = _setup()
    update("off", {})
    assert repo.config.active == "off"
    assert forgotten == [True]
    update("local", {})
    assert forgotten == [True]


def test_other_advisors_sections_are_kept():
    config = AdvisorConfig(active="local", sections={"remote": {"endpoint": "http://keep"}})
    update, repo, *_ = _setup(config)
    update("local", {"endpoint": "http://h"})
    assert repo.config.section("remote") == {"endpoint": "http://keep"}


async def test_test_advisor_reports_the_sample_result():
    *_, registry = _setup()
    message = await TestAdvisor(registry)("local", {})
    assert "fine" in message


async def test_test_advisor_raises_on_bad_config_unknown_and_off():
    *_, registry = _setup()
    test = TestAdvisor(registry)
    with pytest.raises(ValueError, match="bad endpoint"):
        await test("local", {"endpoint": "bad"})
    with pytest.raises(AdvisorConfigError):
        await test("ghost", {})
    with pytest.raises(AdvisorConfigError, match="Choose"):
        await test("off", {})


async def test_test_advisor_times_out():
    registry = AdvisorRegistry()
    registry.register(_spec("slow", keystrokes=False, off_device=False, advisor=_slow))
    with pytest.raises(TimeoutError):
        await TestAdvisor(registry, timeout_s=0.01)("slow", {})
