"""AdvisorRegistry: name -> AdvisorSpec. Created once in `app.py` and passed
in; never a module-level global."""

from __future__ import annotations

from keystrike.domain.advice import NULL_ADVISOR_SPEC, AdvisorSpec


class AdvisorRegistry:
    def __init__(self) -> None:
        self._specs: dict[str, AdvisorSpec] = {NULL_ADVISOR_SPEC.name: NULL_ADVISOR_SPEC}

    def register(self, spec: AdvisorSpec) -> None:
        """Raise `ValueError` on a duplicate name."""
        if spec.name in self._specs:
            raise ValueError(f"advisor {spec.name!r} is already registered")
        self._specs[spec.name] = spec

    def specs(self) -> list[AdvisorSpec]:
        return list(self._specs.values())

    def get(self, name: str) -> AdvisorSpec:
        """Unknown name -> the Null spec (a removed plugin turns advice off)."""
        return self._specs.get(name, NULL_ADVISOR_SPEC)

    def has(self, name: str) -> bool:
        return name in self._specs
