"""Check that every workspace member is configured for release (spec: releases).

release-please only versions what its config lists, so a member left out would never release and
nothing would say so. This compares the config, the manifest and uv.lock with the workspace
members declared in the root pyproject.toml (release-automation design D10). It runs as a test,
inside scripts/check.py; each problem names the member and the file to fix.

Standard library only, like check.py.
"""

import json
import tomllib
from pathlib import Path
from typing import Any

CONFIG = "release-please-config.json"
MANIFEST = ".release-please-manifest.json"
LOCK = "uv.lock"
LINKED_GROUP = "troupe"
"""The linked-versions group: every packages/* member plus the protocol (design D3)."""
PROTOCOL = "protocol"
"""The language-neutral protocol: a component in the linked group, not a workspace member."""


def lock_jsonpath(name: str) -> str:
    """Where release-please finds a package's version in uv.lock (design D4)."""
    return f"$.package[?(@.name.value=='{name}')].version"


def members(root: Path) -> dict[str, str]:
    """Each workspace member's path, relative to root with '/' separators, and its project name."""
    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    found: dict[str, str] = {}
    for pattern in pyproject["tool"]["uv"]["workspace"]["members"]:
        for member in sorted(root.glob(pattern)):
            manifest = member / "pyproject.toml"
            if manifest.is_file():
                project = tomllib.loads(manifest.read_text(encoding="utf-8"))["project"]
                found[member.relative_to(root).as_posix()] = project["name"]
    return found


def problems(root: Path) -> list[str]:
    """Every way the release config, manifest and uv.lock disagree with the workspace."""
    config: dict[str, Any] = json.loads((root / CONFIG).read_text(encoding="utf-8"))
    manifest: dict[str, str] = json.loads((root / MANIFEST).read_text(encoding="utf-8"))
    lock = tomllib.loads((root / LOCK).read_text(encoding="utf-8"))
    workspace = members(root)
    packages: dict[str, dict[str, Any]] = config.get("packages", {})
    found: list[str] = []

    for path, name in workspace.items():
        entry = packages.get(path)
        if entry is None:
            found.append(f"{path} ({name}) has no entry in {CONFIG}: add one under 'packages'.")
        else:
            found.extend(_member_entry_problems(path, name, entry, lock))
        if path not in manifest:
            found.append(f'{path} ({name}) has no version in {MANIFEST}: add "{path}": "0.0.0".')

    known = set(workspace) | {PROTOCOL}
    for path in sorted(set(packages) - known):
        found.append(
            f"{CONFIG} has an entry for {path}, which isn't a workspace member: remove it."
        )
    for path in sorted(set(manifest) - known):
        found.append(
            f"{MANIFEST} has a version for {path}, which isn't a workspace member: remove it."
        )

    found.extend(_protocol_problems(packages.get(PROTOCOL), manifest))
    found.extend(_group_problems(config, workspace))
    return found


def _member_entry_problems(
    path: str, name: str, entry: dict[str, Any], lock: dict[str, Any]
) -> list[str]:
    found: list[str] = []
    for key in ("package-name", "component"):
        if entry.get(key) != name:
            found.append(
                f"{path}'s '{key}' in {CONFIG} is {entry.get(key)!r}: set it to its project name "
                f"{name!r}."
            )
    if entry.get("release-type") != "python":
        found.append(
            f"{path}'s 'release-type' in {CONFIG} is {entry.get('release-type')!r}: set it to "
            "'python'."
        )
    expected = {"type": "toml", "path": f"/{LOCK}", "jsonpath": lock_jsonpath(name)}
    if expected not in entry.get("extra-files", []):
        found.append(
            f"{path} ({name}) doesn't update its version in {LOCK}: add {json.dumps(expected)} to "
            f"its 'extra-files' in {CONFIG}."
        )
    in_lock = [package for package in lock.get("package", []) if package.get("name") == name]
    if len(in_lock) != 1:
        found.append(
            f"{LOCK} has {len(in_lock)} packages named {name!r}, so {path}'s 'extra-files' "
            "JSONPath doesn't match exactly one: run `uv lock`."
        )
    return found


def _protocol_problems(entry: dict[str, Any] | None, manifest: dict[str, str]) -> list[str]:
    if entry is None:
        return [
            f"{PROTOCOL} has no entry in {CONFIG}: add one with 'release-type': 'simple' and "
            f"'component': '{PROTOCOL}'."
        ]
    found: list[str] = []
    if entry.get("release-type") != "simple" or entry.get("component") != PROTOCOL:
        found.append(
            f"{PROTOCOL}'s entry in {CONFIG} needs 'release-type': 'simple' and 'component': "
            f"'{PROTOCOL}'."
        )
    if "extra-files" in entry:
        found.append(
            f"{PROTOCOL}'s entry in {CONFIG} has 'extra-files', but it isn't a Python package and "
            f"has nothing in {LOCK}: remove them."
        )
    if PROTOCOL not in manifest:
        found.append(f'{PROTOCOL} has no version in {MANIFEST}: add "{PROTOCOL}": "0.0.0".')
    return found


def _group_problems(config: dict[str, Any], workspace: dict[str, str]) -> list[str]:
    groups = [
        plugin
        for plugin in config.get("plugins", [])
        if isinstance(plugin, dict)
        and plugin.get("type") == "linked-versions"
        and plugin.get("groupName") == LINKED_GROUP
    ]
    if len(groups) != 1:
        return [
            f"{CONFIG} has {len(groups)} 'linked-versions' plugins named {LINKED_GROUP!r}: keep "
            "exactly one."
        ]
    components = set(groups[0].get("components", []))
    expected = {name for path, name in workspace.items() if path.startswith("packages/")}
    expected.add(PROTOCOL)
    found = [
        f"{component} isn't in the {LINKED_GROUP!r} linked group in {CONFIG}: add it to its "
        "'components'."
        for component in sorted(expected - components)
    ]
    found.extend(
        f"{component} is in the {LINKED_GROUP!r} linked group in {CONFIG}, but only packages/* "
        f"members and {PROTOCOL} belong there: remove it."
        for component in sorted(components - expected)
    )
    return found
