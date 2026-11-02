"""Check that the import contracts cover every plugin, and that the plugin SDK stays dependency-free
(spec: plugin-sdk; runner-sdk design D13).

import-linter checks only the modules a contract names, so a plugin left out of the contract
"plugins import nothing from troupe" would be free to import core. This reads the plugins under
plugins/ and the contracts in the root pyproject.toml, and names each gap:

- each plugin's import package is in `root_packages`, in that contract's sources, and in the
  contract that keeps plugins independent of each other;
- that contract forbids every other workspace package except the plugin SDK;
- the plugin SDK declares no dependencies, so a plugin that uses it inherits nothing else.

It runs as a test, inside scripts/check.py; each problem names the file to fix. Standard library
only, like check.py.
"""

import tomllib
from pathlib import Path
from typing import Any

from release_config import members

PLUGINS = "plugins"
SDK = "troupe_plugin_sdk"
SDK_PATH = "packages/troupe-plugin-sdk"
PLUGINS_CONTRACT = "plugins import nothing from troupe"
INDEPENDENCE_CONTRACT = "plugins are independent of each other"
PYPROJECT = "pyproject.toml"


def import_packages(root: Path, path: str) -> list[str]:
    """The import packages a member's src/ holds: each directory with an __init__.py."""
    src = root / path / "src"
    if not src.is_dir():
        return []
    return sorted(child.name for child in src.iterdir() if (child / "__init__.py").is_file())


def _contract(contracts: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    return next((contract for contract in contracts if contract.get("name") == name), None)


def problems(root: Path) -> list[str]:
    """Every way the import contracts miss a plugin, and every dependency the SDK declares."""
    pyproject = tomllib.loads((root / PYPROJECT).read_text(encoding="utf-8"))
    linter: dict[str, Any] = pyproject["tool"]["importlinter"]
    roots = set(linter.get("root_packages", []))
    contracts: list[dict[str, Any]] = linter.get("contracts", [])
    found: list[str] = []

    packages = {path: import_packages(root, path) for path in members(root)}
    plugins = {
        package: path
        for path, names in packages.items()
        if path.startswith(f"{PLUGINS}/")
        for package in names
    }
    others = {
        package
        for path, names in packages.items()
        if not path.startswith(f"{PLUGINS}/")
        for package in names
        if package != SDK
    }

    contract = _contract(contracts, PLUGINS_CONTRACT)
    independence = _contract(contracts, INDEPENDENCE_CONTRACT)
    if contract is None:
        found.append(
            f'{PYPROJECT} has no import contract named "{PLUGINS_CONTRACT}": add it, with every '
            f"plugin under {PLUGINS}/ as a source, so no plugin can import troupe."
        )
    if independence is None:
        found.append(
            f'{PYPROJECT} has no import contract named "{INDEPENDENCE_CONTRACT}": add it, an '
            f"independence contract naming every plugin under {PLUGINS}/."
        )

    for package, path in sorted(plugins.items()):
        if package not in roots:
            found.append(
                f"{package} ({path}) isn't in [tool.importlinter] root_packages in {PYPROJECT}: "
                "add it, so the import contracts can check it."
            )
        if contract is not None and package not in contract.get("source_modules", []):
            found.append(
                f'{package} ({path}) isn\'t a source of "{PLUGINS_CONTRACT}" in {PYPROJECT}: add '
                "it to the contract's source_modules, so it can't import troupe."
            )
        if independence is not None and package not in independence.get("modules", []):
            found.append(
                f'{package} ({path}) isn\'t in "{INDEPENDENCE_CONTRACT}" in {PYPROJECT}: add it to '
                "the contract's modules, so plugins don't import each other."
            )

    if contract is not None:
        forbidden = set(contract.get("forbidden_modules", []))
        if SDK in forbidden:
            found.append(
                f'"{PLUGINS_CONTRACT}" in {PYPROJECT} forbids {SDK}: remove it, since plugins '
                "build on the plugin SDK."
            )
        for package in sorted(others - forbidden):
            found.append(
                f'"{PLUGINS_CONTRACT}" in {PYPROJECT} doesn\'t forbid {package}: add it to the '
                "contract's forbidden_modules, since a plugin imports only the plugin SDK."
            )

    sdk = root / SDK_PATH / PYPROJECT
    if sdk.is_file():
        project = tomllib.loads(sdk.read_text(encoding="utf-8"))["project"]
        for requirement in project.get("dependencies", []):
            found.append(
                f"{SDK_PATH}/{PYPROJECT} depends on {requirement!r}: remove it. The plugin SDK "
                "uses the standard library only, so a plugin inherits nothing else."
            )
    else:
        found.append(f"{SDK_PATH}/{PYPROJECT} doesn't exist: the plugins build on the plugin SDK.")
    return found
