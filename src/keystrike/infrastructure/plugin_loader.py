"""Discover advisor plugins through Python entry points and register them."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from importlib.metadata import entry_points as _entry_points
from typing import Any, Protocol

from keystrike.domain.advice import PLUGIN_API_VERSION, AdvisorSpec

logger = logging.getLogger(__name__)

ENTRY_POINT_GROUP = "keystrike.advisors"


class SpecRegistry(Protocol):
    """Shape of `application.advisor_registry.AdvisorRegistry`."""

    def register(self, spec: AdvisorSpec) -> None: ...


class EntryPointLike(Protocol):
    name: str

    def load(self) -> Any: ...


def _installed() -> Iterable[EntryPointLike]:
    return _entry_points(group=ENTRY_POINT_GROUP)


def load_plugins(
    registry: SpecRegistry,
    entry_points: Callable[[], Iterable[EntryPointLike]] = _installed,
) -> list[str]:
    """Import every entry-point module, check `API_VERSION`, call
    `register()`. A failing plugin is skipped; its error is returned (one
    string per failure) so the UI can show it."""
    errors: list[str] = []
    for ep in entry_points():
        try:
            module = ep.load()
            version = getattr(module, "API_VERSION", None)
            if version != PLUGIN_API_VERSION:
                errors.append(
                    f"plugin {ep.name!r} needs plugin API {version!r}, "
                    f"this keystrike has {PLUGIN_API_VERSION}"
                )
                continue
            module.register(registry)
        except Exception as exc:
            logger.warning("plugin %s failed to load: %s", ep.name, exc)
            errors.append(f"plugin {ep.name!r} failed to load: {type(exc).__name__}: {exc}")
    return errors
