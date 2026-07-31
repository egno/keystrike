"""Fitness functions for the ports-and-adapters layering described in PLAN.md §2:
`presentation -> application -> domain <- infrastructure`. Composition-root and
entry-point files (`app.py`, `cli.py`, `__main__.py`) are exempt — they're the
one place allowed to see every layer.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

_SRC = Path(__file__).parent.parent / "src" / "keystrike"
_EXEMPT_FILES = {"app.py", "cli.py", "__main__.py"}

# Which other keystrike layers each layer is allowed to import from.
_ALLOWED_DEPENDENCIES: dict[str, set[str]] = {
    "domain": set(),
    "application": {"domain"},
    "infrastructure": {"domain"},
    "presentation": {"domain", "application"},
}


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            modules.add(node.module)
    return modules


def _layer_files(layer: str) -> list[Path]:
    return [path for path in (_SRC / layer).rglob("*.py") if path.name not in _EXEMPT_FILES]


def test_layers_only_depend_on_allowed_keystrike_layers():
    violations: list[str] = []
    for layer, allowed in _ALLOWED_DEPENDENCIES.items():
        allowed_prefixes = {f"keystrike.{name}" for name in allowed} | {f"keystrike.{layer}"}
        for path in _layer_files(layer):
            for module in _imported_modules(path):
                if not (module == "keystrike" or module.startswith("keystrike.")):
                    continue
                if any(module == p or module.startswith(f"{p}.") for p in allowed_prefixes):
                    continue
                rel = path.relative_to(_SRC)
                violations.append(f"{rel} (layer={layer!r}) imports disallowed module {module!r}")

    assert not violations, "Layering violations:\n" + "\n".join(violations)


def test_domain_has_no_third_party_imports():
    stdlib = sys.stdlib_module_names
    violations: list[str] = []
    for path in _layer_files("domain"):
        for module in _imported_modules(path):
            top = module.split(".")[0]
            if top == "keystrike":
                continue
            if top not in stdlib:
                rel = path.relative_to(_SRC)
                violations.append(f"{rel} imports non-stdlib module {module!r}")

    assert not violations, "Domain purity violations:\n" + "\n".join(violations)


def test_presentation_has_no_path_reads():
    violations: list[str] = []
    for path in _layer_files("presentation"):
        for module in _imported_modules(path):
            if module == "pathlib" or module.startswith("pathlib."):
                rel = path.relative_to(_SRC)
                violations.append(f"{rel} imports {module!r}")

    assert not violations, "Presentation Path violations:\n" + "\n".join(violations)
