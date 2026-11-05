"""Use cases for the advisor settings: choose the active advisor, confirm
sending data off the device, and try an advisor on sample data."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace

from keystrike.application.advisor_context import sample_context
from keystrike.application.advisor_registry import AdvisorRegistry
from keystrike.domain.advice import (
    NULL_ADVISOR_NAME,
    AdvisorConfig,
    AdvisorSpec,
    validate_advice,
)
from keystrike.domain.protocols import AdvisorConfigRepository, KeystrokeArchive

OFF_DEVICE_NOTICE = (
    "{label} sends practice data to a server: per-key statistics, mistyped "
    "keys and errors per finger. Save again to confirm."
)


class AdvisorConfigError(ValueError):
    """Raised by UpdateAdvisorConfig when a proposed change is invalid."""


class OffDeviceConfirmationRequired(AdvisorConfigError):
    """The chosen advisor sends data off the device and the user has not
    confirmed it yet. The message is the notice to show."""


def _noop() -> None:
    pass


@dataclass(slots=True)
class UpdateAdvisorConfig:
    """Validate and save the active advisor and its settings. Choosing an
    advisor that does not need keystrokes deletes the raw keystroke archive;
    choosing "off" also deletes the kept advice."""

    repo: AdvisorConfigRepository
    registry: AdvisorRegistry
    archive: KeystrokeArchive | None = None
    forget_advice: Callable[[], None] = _noop

    def check(
        self,
        active: str,
        values: Mapping[str, str],
        *,
        confirm_off_device: bool = False,
    ) -> None:
        """Raise `AdvisorConfigError` (or `OffDeviceConfirmationRequired`)
        if saving would fail. Saves nothing, so a screen can reject a form
        before it saves anything else."""
        self._validated(active, values, confirm_off_device=confirm_off_device)

    def _validated(
        self,
        active: str,
        values: Mapping[str, str],
        *,
        confirm_off_device: bool,
    ) -> tuple[AdvisorSpec, dict[str, str], tuple[str, ...]]:
        if not self.registry.has(active):
            raise AdvisorConfigError(f"Unknown advisor {active!r}.")
        spec = self.registry.get(active)
        section = {k: v.strip() for k, v in values.items()}
        try:
            spec.create(section)
        except ValueError as exc:
            raise AdvisorConfigError(str(exc)) from exc
        confirmed = self.repo.load().confirmed_off_device
        if spec.capabilities.sends_data_off_device and active not in confirmed:
            if not confirm_off_device:
                raise OffDeviceConfirmationRequired(OFF_DEVICE_NOTICE.format(label=spec.label))
            confirmed = (*confirmed, active)
        return spec, section, confirmed

    def __call__(
        self,
        active: str,
        values: Mapping[str, str],
        *,
        confirm_off_device: bool = False,
    ) -> AdvisorConfig:
        spec, section, confirmed = self._validated(
            active, values, confirm_off_device=confirm_off_device
        )
        current = self.repo.load()
        sections = dict(current.sections)
        if spec.settings:
            sections[active] = section
        config = replace(current, active=active, confirmed_off_device=confirmed, sections=sections)
        self.repo.save(config)
        if not spec.capabilities.needs_keystrokes and self.archive is not None:
            # a failure is retried on the next finished session
            with contextlib.suppress(OSError):
                self.archive.clear()
        if active == NULL_ADVISOR_NAME:
            self.forget_advice()
        return config


@dataclass(slots=True)
class TestAdvisor:
    """Run one advisor (its settings not yet saved) on sample data and
    report whether it gave valid advice."""

    __test__ = False  # not a pytest class

    registry: AdvisorRegistry
    timeout_s: float = 30.0

    async def __call__(self, active: str, values: Mapping[str, str]) -> str:
        """A short success message; raises on any failure."""
        if not self.registry.has(active):
            raise AdvisorConfigError(f"Unknown advisor {active!r}.")
        spec = self.registry.get(active)
        if active == NULL_ADVISOR_NAME:
            raise AdvisorConfigError("Choose an advisor first.")
        advisor = spec.create({k: v.strip() for k, v in values.items()})
        ctx = sample_context()
        advice = await asyncio.wait_for(advisor(ctx), self.timeout_s)
        advice = validate_advice(advice, ctx.course)
        return f"{spec.label}: ok — {advice.summary or 'replied without a summary'}"
