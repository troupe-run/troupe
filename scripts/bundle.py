"""Check that the troupe-run bundle installs troupe with everything it bundles (spec: installation).

Core finds its adapters by entry point and starts its runners in its own environment, so an install
needs every workspace member beside it. troupe-run depends on all of them, and core on none but the
plugin SDK, whose runner contract types it uses (install-with-uv design D1, D6; runner-sdk D12).
Its `troupe` command must be core's own (design D2). When the bundle pins a component, it pins each
released workspace member that component depends on too, so a tag install never looks one up on a
package index (runner-sdk D12). It runs as a test, inside scripts/check.py; each problem names the
package and the file to fix.

A runner plugin that depends on anything beyond the plugin SDK is an optional extra of troupe-run,
named exactly as core's runner table names its runner, and 'all' names every one; a plugin that
depends only on the SDK is in the base install. Core's table says which runners are in an extra,
and agrees with where each plugin's own dependencies put it (runner-extras design D2, D4, D5; owner,
#333).

Standard library only, like check.py.
"""

import ast
import json
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from release_config import (
    MANIFEST,
    bundle_requirements,
    members,
    normalise,
    pinned_version,
    requirement_name,
)

BUNDLE = "troupe-run"
BUNDLE_PYPROJECT = "packages/troupe-run/pyproject.toml"
CORE = "troupe"
CORE_PYPROJECT = "packages/troupe/pyproject.toml"
SDK = "troupe-plugin-sdk"
"""The one workspace member core depends on: the runner contract's types live there (spec:
installation, plugin-sdk)."""
UNRELEASED = "0.0.0"
COMMAND = "troupe"
ALL = "all"
"""The extra that installs every runner (runner-extras design D4)."""
RUNNER_TABLE = "packages/troupe/src/troupe/core/interim.py"
"""Core's table of the runners it knows: each runner's name, package and whether it's in an extra
(runner-extras design D5). Read as source, never imported, like the manifests."""
PLUGINS = "plugins/"


@dataclass(frozen=True)
class Runner:
    """A runner in core's table, as the bundle check reads it."""

    name: str
    package: str
    in_extra: bool


def runner_table(root: Path) -> list[Runner] | None:
    """The runners core's table names, in its order, or None when there's no table to read."""
    file = root / RUNNER_TABLE
    if not file.is_file():
        return None
    for node in ast.parse(file.read_text(encoding="utf-8")).body:
        target: ast.expr
        if isinstance(node, ast.AnnAssign):
            target, value = node.target, node.value
        elif isinstance(node, ast.Assign) and len(node.targets) == 1:
            target, value = node.targets[0], node.value
        else:
            continue
        if not (isinstance(target, ast.Name) and target.id == "RUNNERS"):
            continue
        if not isinstance(value, ast.Dict):
            return None
        found: list[Runner] = []
        for key, entry in zip(value.keys, value.values, strict=True):
            if not (isinstance(key, ast.Constant) and isinstance(entry, ast.Call)):
                return None
            fields = {
                k.arg: k.value.value
                for k in entry.keywords
                if k.arg is not None and isinstance(k.value, ast.Constant)
            }
            found.append(
                Runner(str(key.value), str(fields.get("package")), fields.get("in_extra") is True)
            )
        return found
    return None


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

    libraries = _libraries(root, workspace)
    wanted = sorted(name for name in workspace if name != BUNDLE)
    have = {requirement_name(r) for _, r in bundle_requirements(bundle)}
    for name in wanted:
        if name not in have and name not in libraries:
            found.append(
                f"{name} ({workspace[name]}) isn't a dependency of {BUNDLE}: add "
                f'"{name}" to the dependencies in {BUNDLE_PYPROJECT}, so an install brings it.'
            )
    for name in sorted(have - set(wanted)):
        found.append(
            f"{BUNDLE} depends on {name}, which isn't a workspace member: remove it from the "
            f"dependencies in {BUNDLE_PYPROJECT}."
        )

    found.extend(_extra_problems(root, workspace, bundle, libraries))

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
    held = {requirement_name(r): r for _, r in bundle_requirements(bundle)}

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


def _libraries(root: Path, workspace: dict[str, str]) -> dict[str, list[str]]:
    """Each plugin that depends on more than the SDK, with what else it depends on, by name."""
    found: dict[str, list[str]] = {}
    for name, path in workspace.items():
        if not path.startswith(PLUGINS):
            continue
        project = _project(root, f"{path}/pyproject.toml") or {}
        others = [
            requirement_name(r)
            for r in project.get("dependencies", [])
            if requirement_name(r) != SDK
        ]
        if others:
            found[name] = others
    return found


def _extra_problems(
    root: Path, workspace: dict[str, str], bundle: dict[str, Any], libraries: dict[str, list[str]]
) -> list[str]:
    """Where each runner plugin is, against where its dependencies put it, the extras' names, 'all'
    and core's table (spec: installation; runner-extras design D2, D4, D5)."""
    table = runner_table(root)
    if table is None:
        return [
            f"{RUNNER_TABLE} doesn't exist, or has no RUNNERS table: the bundle check reads each "
            "runner's name, and whether it's in an extra, from it."
        ]
    by_package = {runner.package: runner for runner in table}
    runner_names = {runner.name for runner in table}

    def runner_of(name: str) -> Runner | None:
        return by_package.get(name.replace("-", "_"))

    extras: dict[str, list[str]] = bundle.get("optional-dependencies", {})
    base = {requirement_name(r) for r in bundle.get("dependencies", [])}
    found: list[str] = []

    for extra, requirements in extras.items():
        if extra == ALL or extra in runner_names:
            continue
        held = [requirement_name(r) for r in requirements]
        owners = [(n, r) for n in held if (r := runner_of(n)) is not None]
        problem = (
            f"{BUNDLE}'s extra {extra!r} isn't named after a runner core knows ({RUNNER_TABLE}): "
            f"{BUNDLE}'s extras are its runners', each named exactly as core's runner table names "
            "it, and 'all'."
        )
        if owners:
            holder, owner = owners[0]
            problem += (
                f" It holds {holder}, whose runner is {owner.name!r}: rename the extra to "
                f"{owner.name!r} in {BUNDLE_PYPROJECT}."
            )
        else:
            problem += f" Remove it from {BUNDLE_PYPROJECT}."
        found.append(problem)

    in_some_extra = {
        requirement_name(r) for extra, rs in extras.items() if extra != ALL for r in rs
    }
    for name, path in sorted(workspace.items(), key=lambda item: item[1]):
        if not path.startswith(PLUGINS):
            continue
        runner = runner_of(name)
        others = libraries.get(name)
        if others is not None:
            what = ", ".join(others)
            if runner is None:
                found.append(
                    f"{name} ({path}) depends on {what}, beyond {SDK}, but core's runner table "
                    f"({RUNNER_TABLE}) has no runner whose package is {name.replace('-', '_')}: "
                    "add its entry there, so its extra can be named after it."
                )
                continue
            if name in base:
                found.append(
                    f"{name} ({path}) depends on {what}, beyond {SDK}, so it's an optional extra "
                    f"of {BUNDLE}: move it from the dependencies in {BUNDLE_PYPROJECT} to its "
                    f"runner's extra, {runner.name!r}, and to 'all'."
                )
            elif name not in in_some_extra:
                found.append(
                    f"{name} ({path}) depends on {what}, beyond {SDK}, so {BUNDLE} has it in an "
                    f"extra named after its runner: add it to the {runner.name!r} extra, and to "
                    f"'all', in {BUNDLE_PYPROJECT}."
                )
        else:
            for extra, requirements in extras.items():
                if extra != ALL and name in {requirement_name(r) for r in requirements}:
                    found.append(
                        f"{BUNDLE} has {name} in its {extra!r} extra, but {path} depends only on "
                        f"{SDK}, so it's in the base install: move it to the dependencies in "
                        f"{BUNDLE_PYPROJECT}, and remove the extra."
                    )
        if runner is not None and runner.in_extra != (others is not None):
            if others is not None:
                found.append(
                    f"core's runner table ({RUNNER_TABLE}) says the {runner.name!r} runner is in "
                    f"the base install, but {name} depends on more than {SDK}, so {BUNDLE} has it "
                    "in an extra: set in_extra=True on its entry."
                )
            else:
                found.append(
                    f"core's runner table ({RUNNER_TABLE}) says the {runner.name!r} runner is in "
                    f"an extra, but {name} depends only on {SDK}, so it's in the base install: set "
                    "in_extra=False on its entry."
                )

    if ALL not in extras:
        found.append(
            f"{BUNDLE} has no 'all' extra: add all = [...] under [project.optional-dependencies] "
            f"in {BUNDLE_PYPROJECT}, naming every runner in an extra, so {BUNDLE}[all] installs "
            "every runner."
        )
        return found
    in_all = {requirement_name(r): r for r in extras[ALL]}
    held_by: dict[str, tuple[str, str]] = {}
    for extra, requirements in extras.items():
        if extra != ALL:
            for requirement in requirements:
                held_by.setdefault(requirement_name(requirement), (extra, requirement))
    for name, (extra, requirement) in held_by.items():
        if name not in in_all:
            found.append(
                f"{BUNDLE}'s 'all' extra doesn't name {name}, which its {extra!r} extra holds: add "
                f"{requirement!r} to 'all' in {BUNDLE_PYPROJECT}."
            )
        elif in_all[name] != requirement:
            found.append(
                f"{BUNDLE}'s 'all' extra names {in_all[name]!r}, but its {extra!r} extra names "
                f"{requirement!r}: make them the same in {BUNDLE_PYPROJECT}."
            )
    for name in in_all:
        if name not in held_by:
            found.append(
                f"{BUNDLE}'s 'all' extra names {name}, which no runner's extra holds: remove it "
                f"from 'all' in {BUNDLE_PYPROJECT}."
            )
    return found
