"""Check that the troupe-run bundle installs troupe with everything it bundles (spec: installation).

Core finds its adapters by entry point and starts its runners in its own environment, so an install
needs every workspace member beside it. troupe-run depends on all of them, and core on none
(install-with-uv design D1, D6). Its `troupe` command must be core's own (design D2). It runs as a
test, inside scripts/check.py; each problem names the package and the file to fix.

Standard library only, like check.py.
"""

import tomllib
from pathlib import Path
from typing import Any

from release_config import members, normalise, requirement_name

BUNDLE = "troupe-run"
BUNDLE_PYPROJECT = "packages/troupe-run/pyproject.toml"
CORE = "troupe"
CORE_PYPROJECT = "packages/troupe/pyproject.toml"
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
        if name in workspace:
            found.append(
                f"{CORE} depends on {name} in {CORE_PYPROJECT}, but core declares no dependency on "
                f"a workspace member: remove it there. {BUNDLE} ({BUNDLE_PYPROJECT}) is what "
                "brings it into an install."
            )

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
