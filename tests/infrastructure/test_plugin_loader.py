from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from keystrike.application.advisor_registry import AdvisorRegistry
from keystrike.domain.advice import PLUGIN_API_VERSION, AdvisorCapabilities, AdvisorSpec
from keystrike.infrastructure.plugin_loader import ENTRY_POINT_GROUP, SpecRegistry, load_plugins


def _spec(name: str) -> AdvisorSpec:
    return AdvisorSpec(name, name, AdvisorCapabilities(), (), lambda _cfg: None)  # type: ignore[arg-type,return-value]


class _EntryPoint:
    def __init__(self, name: str, module: Any = None, error: Exception | None = None) -> None:
        self.name = name
        self._module = module
        self._error = error

    def load(self) -> Any:
        if self._error is not None:
            raise self._error
        return self._module


def _plugin(name: str, version: int = PLUGIN_API_VERSION) -> Any:
    def register(reg: SpecRegistry) -> None:
        reg.register(_spec(name))

    return SimpleNamespace(API_VERSION=version, register=register)


def test_group_name():
    assert ENTRY_POINT_GROUP == "keystrike.advisors"


def test_a_good_plugin_is_registered():
    registry = AdvisorRegistry()
    errors = load_plugins(registry, lambda: [_EntryPoint("llm", _plugin("llm"))])
    assert errors == []
    assert registry.has("llm")


def test_api_version_mismatch_is_skipped_with_an_error():
    registry = AdvisorRegistry()
    errors = load_plugins(registry, lambda: [_EntryPoint("old", _plugin("old", version=0))])
    assert not registry.has("old")
    assert len(errors) == 1
    assert "old" in errors[0]
    assert "API" in errors[0]


def test_a_plugin_without_a_version_is_skipped():
    registry = AdvisorRegistry()
    errors = load_plugins(registry, lambda: [_EntryPoint("x", SimpleNamespace(register=None))])
    assert len(errors) == 1


def test_a_register_that_raises_does_not_stop_the_others():
    def boom(_reg: Any) -> None:
        raise RuntimeError("nope")

    registry = AdvisorRegistry()
    entries = [
        _EntryPoint("bad", SimpleNamespace(API_VERSION=PLUGIN_API_VERSION, register=boom)),
        _EntryPoint("good", _plugin("good")),
    ]
    errors = load_plugins(registry, lambda: entries)
    assert registry.has("good")
    assert len(errors) == 1
    assert "RuntimeError" in errors[0]


def test_an_import_error_is_reported():
    registry = AdvisorRegistry()
    errors = load_plugins(registry, lambda: [_EntryPoint("gone", error=ImportError("no module"))])
    assert len(errors) == 1
    assert "gone" in errors[0]


def test_a_duplicate_name_is_reported_and_the_first_wins():
    registry = AdvisorRegistry()
    entries = [_EntryPoint("a", _plugin("same")), _EntryPoint("b", _plugin("same"))]
    errors = load_plugins(registry, lambda: entries)
    assert len(errors) == 1
    assert "already registered" in errors[0]
    assert registry.has("same")
