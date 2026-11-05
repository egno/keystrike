"""Contract test: every registered advisor spec gives a valid `LessonAdvice`
on a sample context within its time budget. Plugins found by entry point are
included, so a plugin that breaks the contract fails the core's suite."""

from __future__ import annotations

import asyncio

import pytest

from keystrike.advisors import rules
from keystrike.application.advisor_context import sample_context
from keystrike.application.advisor_registry import AdvisorRegistry
from keystrike.domain.advice import AdvisorSpec, LessonAdvice, validate_advice
from keystrike.infrastructure.plugin_loader import load_plugins


def _registry() -> AdvisorRegistry:
    registry = AdvisorRegistry()
    rules.register(registry)
    assert load_plugins(registry) == []
    return registry


SPECS = _registry().specs()


@pytest.mark.parametrize("spec", SPECS, ids=lambda s: s.name)
def test_spec_is_well_formed(spec: AdvisorSpec):
    assert spec.name
    assert spec.label
    assert len({f.name for f in spec.settings}) == len(spec.settings)
    for field in spec.settings:
        assert field.default in field.choices or not field.choices


@pytest.mark.parametrize(
    "spec", [s for s in SPECS if not s.capabilities.sends_data_off_device], ids=lambda s: s.name
)
async def test_local_advisors_give_valid_advice_within_the_budget(spec: AdvisorSpec):
    """Advisors that call a server are tested by their own package with a fake client."""
    ctx = sample_context()
    defaults = {f.name: f.default for f in spec.settings}
    advisor = spec.create(defaults)
    advice = await asyncio.wait_for(advisor(ctx), timeout=0.15)
    assert isinstance(advice, LessonAdvice)
    checked = validate_advice(advice, ctx.course)
    assert validate_advice(checked, ctx.course) == checked  # validation is idempotent
    assert all(r.applied > 0 for r in checked.recommendations)


def test_installed_plugins_load_without_errors():
    assert {s.name for s in SPECS} >= {"off", "rules"}
