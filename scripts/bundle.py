"""Check that the troupe-run bundle installs troupe with everything it bundles (spec: installation).

Core finds its adapters by entry point and starts its runners in its own environment, so an install
needs every workspace member beside it. troupe-run depends on all of them, and core on none but the
plugin SDK, whose runner contract types it uses (install-with-uv design D1, D6; runner-sdk D12).
Its `troupe` command must be core's own (design D2). When the bundle pins a component, it pins each
released workspace member that component depends on too, so a tag install never looks one up on a
package index (runner-sdk D12). It runs as a test, inside scripts/check.py; each problem names the
package and the file to fix.

Standard library only, like check.py.
"""

import json
import tomllib
from pathlib import Path
from typing import Any

from release_config import MANIFEST, members, normalise, pinned_version, requirement_name

BUNDLE = "troupe-run"
BUNDLE_PYPROJECT = "packages/troupe-run/pyproject.toml"
CORE = "troupe"
CORE_PYPROJECT = "packages/troupe/pyproject.toml"
SDK = "troupe-plugin-sdk"
"""The one workspace member core depends on: the runner contract's types live there (spec:
installation, plugin-sdk)."""
UNRELEASED = "0.0.0"
COMMAND = "troupe"


def _project(root: Path, path: str) -> dict[str, Any] | None:
    file = root / path
    if not file.is_file():
        return None
    project: dict[str, Any] = tomllib.loads(file.read_text(encoding="utf-8"))["project"]
    return project


def problems(root: Path) -> list[str]:
    """Every way the bundle's dependencies, core's dependencies and the two commands disagree."""
    workspace = {normalise(name): path for path, name in members(root).items()}
    bundle = _project(root, BUNDLE_PYPROJECT)
    core = _project(root, CORE_PYPROJECT)
    if bundle is None:
        return [
            f"{BUNDLE_PYPROJECT} doesn't exist: the {BUNDLE} package installs troupe with "
            "everything it bundles, so every workspace member needs it."
        ]
    if core is None:
        return [f"{CORE_PYPROJECT} doesn't exist: troupe-run depends on core."]
    found: list[str] = []

    wanted = sorted(name for name in workspace if name != BUNDLE)
    have = {requirement_name(r) for r in bundle.get("dependencies", [])}
    for name in wanted:
        if name not in have:
            found.append(
                f"{name} ({workspace[name]}) isn't a dependency of {BUNDLE}: add "
                f'"{name}" to the dependencies in {BUNDLE_PYPROJECT}, so an install brings it.'
            )
    for name in sorted(have - set(wanted)):
        found.append(
            f"{BUNDLE} depends on {name}, which isn't a workspace member: remove it from the "
            f"dependencies in {BUNDLE_PYPROJECT}."
        )

    for requirement in core.get("dependencies", []):
        name = requirement_name(requirement)
        if name in workspace and name != SDK:
            found.append(
                f"{CORE} depends on {name} in {CORE_PYPROJECT}, but core declares no dependency on "
                f"a workspace member but {SDK}: remove it there. {BUNDLE} ({BUNDLE_PYPROJECT}) is "
                "what brings it into an install."
            )

    found.extend(_unpinned_dependencies(root, workspace, bundle))

    expected = core.get("scripts", {}).get(COMMAND)
    actual = bundle.get("scripts", {}).get(COMMAND)
    if actual != expected:
        if actual is None:
            runs = f"{BUNDLE} declares no troupe command"
        else:
            runs = f"{BUNDLE}'s troupe command runs {actual!r}"
        found.append(
            f"{runs}, but {CORE}'s runs {expected!r}: set [project.scripts] "
            f"{COMMAND} = {expected!r} in {BUNDLE_PYPROJECT}."
        )
    return found


def _unpinned_dependencies(
    root: Path, workspace: dict[str, str], bundle: dict[str, Any]
) -> list[str]:
    """Each released workspace member that a component the bundle pins depends on, but that the
    bundle names bare (installation spec; runner-sdk D12). An unreleased member can't be pinned yet,
    so it's left out. A malformed pin is the release config check's to report."""
    manifest_file = root / MANIFEST
    manifest: dict[str, str] = (
        json.loads(manifest_file.read_text(encoding="utf-8")) if manifest_file.is_file() else {}
    )
    held = {requirement_name(r): r for r in bundle.get("dependencies", [])}

    def pinned(name: str) -> bool:
        try:
            return name in held and pinned_version(held[name], name, workspace[name]) is not None
        except ValueError:
            return True

    found: list[str] = []
    for name in sorted(held):
        if name not in workspace or not pinned(name):
            continue
        project = _project(root, f"{workspace[name]}/pyproject.toml") or {}
        for requirement in project.get("dependencies", []):
            needed = requirement_name(requirement)
            if needed not in workspace or needed not in held or pinned(needed):
                continue
            if manifest.get(workspace[needed], UNRELEASED) == UNRELEASED:
                continue
            found.append(
                f"{BUNDLE} pins {name}, which depends on {needed}, but names {needed} bare in "
                f"{BUNDLE_PYPROJECT}: pin it at its latest release too, so an install of the "
                "bundle's tag never looks it up on a package index."
            )
    return found
