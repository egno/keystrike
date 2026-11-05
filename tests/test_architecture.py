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


_PACKAGES = _SRC.parent.parent / "packages"
_NETWORK_MODULES = {"urllib", "http", "socket", "ssl", "ftplib", "smtplib", "xmlrpc"}
# Word-list import and git sync use the network, and only when the user starts them.
_NETWORK_ALLOWED_PREFIXES = ("wordlist_", "sync_")


def _only_keystrike_imports(files: list[Path], allowed: set[str], *, what: str) -> list[str]:
    violations: list[str] = []
    for path in files:
        for module in _imported_modules(path):
            if not (module == "keystrike" or module.startswith("keystrike.")):
                continue
            if any(module == p or module.startswith(f"{p}.") for p in allowed):
                continue
            violations.append(f"{path.name} ({what}) imports {module!r}")
    return violations


def test_builtin_advisors_import_only_domain_and_plugin_api():
    files = list((_SRC / "advisors").rglob("*.py"))
    assert files
    allowed = {"keystrike.domain", "keystrike.plugin_api", "keystrike.advisors"}
    violations = _only_keystrike_imports(files, allowed, what="advisors")
    assert not violations, "Advisor rule violations:\n" + "\n".join(violations)


def test_plugin_api_facade_imports_only_domain_and_application():
    allowed = {"keystrike.domain", "keystrike.application"}
    violations = _only_keystrike_imports([_SRC / "plugin_api.py"], allowed, what="plugin_api")
    assert not violations, "Facade rule violations:\n" + "\n".join(violations)


def test_plugin_packages_import_only_the_plugin_api_from_keystrike():
    files = [p for p in _PACKAGES.rglob("src/**/*.py")]
    assert files
    violations = _only_keystrike_imports(files, {"keystrike.plugin_api"}, what="plugin package")
    # `import keystrike` alone is also not the facade.
    for path in files:
        if "keystrike" in _imported_modules(path):
            violations.append(f"{path.name} imports bare 'keystrike'")
    assert not violations, "Plugin package violations:\n" + "\n".join(violations)


def test_core_has_no_network_code_outside_wordlist_and_sync_modules():
    """'Fully local' is checked, not promised: advice leaves the device only
    through a plugin the user installed."""
    violations: list[str] = []
    for path in _SRC.rglob("*.py"):
        if path.name.startswith(_NETWORK_ALLOWED_PREFIXES):
            continue
        for module in _imported_modules(path):
            if module.split(".")[0] in _NETWORK_MODULES:
                violations.append(f"{path.relative_to(_SRC)} imports {module!r}")
    assert not violations, "Network imports in the core:\n" + "\n".join(violations)
