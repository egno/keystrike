from __future__ import annotations

import pytest

from keystrike.application.advisor_registry import AdvisorRegistry
from keystrike.domain.advice import NULL_ADVISOR_SPEC, AdvisorCapabilities, AdvisorSpec


def _spec(name: str) -> AdvisorSpec:
    return AdvisorSpec(name, name.title(), AdvisorCapabilities(), (), lambda _cfg: None)  # type: ignore[arg-type,return-value]


def test_null_advisor_is_always_registered():
    assert AdvisorRegistry().specs() == [NULL_ADVISOR_SPEC]


def test_register_and_get():
    registry = AdvisorRegistry()
    spec = _spec("rules")
    registry.register(spec)
    assert registry.get("rules") is spec
    assert [s.name for s in registry.specs()] == ["off", "rules"]


def test_duplicate_name_is_rejected():
    registry = AdvisorRegistry()
    registry.register(_spec("rules"))
    with pytest.raises(ValueError, match="already registered"):
        registry.register(_spec("rules"))
    with pytest.raises(ValueError, match="already registered"):
        registry.register(_spec("off"))


def test_unknown_name_turns_advice_off():
    registry = AdvisorRegistry()
    assert registry.get("removed-plugin") is NULL_ADVISOR_SPEC
    assert not registry.has("removed-plugin")
