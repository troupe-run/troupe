"""Check that every workspace member is configured for release (spec: releases).

release-please only versions what its config lists, so a member left out would never release and
nothing would say so. This compares the config, the manifest and uv.lock with the workspace
members declared in the root pyproject.toml (release-automation design D10), and the protocol
version the troupe package records with the manifest's (protocol-own-release D3). It runs as a test,
inside scripts/check.py; each problem names the member and the file to fix.

Standard library only, like check.py.
"""

import json
import re
import tomllib
from pathlib import Path
from typing import Any

CONFIG = "release-please-config.json"
MANIFEST = ".release-please-manifest.json"
LOCK = "uv.lock"
LINKED_GROUP = "troupe"
"""The linked-versions group: every packages/* member and everything the bundle ships, so the bundle
is the latest release of everything in it (release-automation design D3; runners-in-linked-group
design D1)."""
PROTOCOL = "protocol"
"""The language-neutral protocol: released on its own, and not a workspace member
(protocol-own-release design D1)."""
PROTOCOL_RECORD = "packages/troupe/src/troupe/protocol/version.json"
"""Where the troupe package records the protocol version its copy of the schemas is. Only a
protocol release pull request changes it (protocol-own-release design D2)."""
RECORD_UPDATE = {"type": "json", "path": f"/{PROTOCOL_RECORD}", "jsonpath": "$.version"}
"""The protocol's extra-file update that writes its new version into PROTOCOL_RECORD."""
BUNDLE = "troupe-run"
"""The bundle the documented install command installs (install-with-uv design D1). Its release tag,
troupe-run-v<version>, is the one the docs name (install-from-tag design D1). Named, not given as
its path: a path into packages/ here would make every suite that imports this reach every package
(check_paths_reach.py, rule 4)."""
TAGGED_PAGES = ("README.md", "docs/opening-night/install.md")
"""The pages whose install command each release moves to the bundle's new tag: release-please's
generic updater rewrites the version between their markers (install-from-tag design D3)."""


def page_update(page: str) -> dict[str, str]:
    """The bundle's extra-file update that moves the version between a page's markers."""
    return {"type": "generic", "path": f"/{page}"}


def bundle_path(root: Path) -> str:
    """The bundle's path in the release config: the entry released under its name."""
    config: dict[str, Any] = json.loads((root / CONFIG).read_text(encoding="utf-8"))
    entries: dict[str, dict[str, Any]] = config["packages"]
    [path] = [path for path, entry in entries.items() if entry.get("package-name") == BUNDLE]
    return path


def bundle_version(root: Path) -> str:
    """The bundle's released version in the manifest: 0.0.0 until its first release."""
    manifest: dict[str, str] = json.loads((root / MANIFEST).read_text(encoding="utf-8"))
    return manifest[bundle_path(root)]


def lock_jsonpath(name: str) -> str:
    """Where release-please finds a package's version in uv.lock (design D4)."""
    return f"$.package[?(@.name.value=='{name}')].version"


def normalise(name: str) -> str:
    """A distribution name as packaging compares it (PEP 503)."""
    return re.sub(r"[-_.]+", "-", name).lower()


def requirement_name(requirement: str) -> str:
    """The distribution a requirement names, without its extras, markers or version."""
    match = re.match(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)", requirement)
    if match is None:
        raise ValueError(f"not a requirement: {requirement!r}")
    return normalise(match.group(1))


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


def bundled(root: Path) -> set[str] | None:
    """The workspace members the bundle depends on, by project name, or None when the bundle isn't
    a member, which bundle.py reports (runners-in-linked-group design D2)."""
    workspace = members(root)
    paths = [path for path, name in workspace.items() if name == BUNDLE]
    if not paths:
        return None
    project = tomllib.loads((root / paths[0] / "pyproject.toml").read_text(encoding="utf-8"))
    names = {normalise(name): name for name in workspace.values()}
    wanted = {requirement_name(r) for r in project["project"].get("dependencies", [])}
    return {names[name] for name in wanted if name in names}


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
            found.append(_missing_version(path, name))

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
    found.extend(_record_problems(root, manifest))
    found.extend(_group_problems(config, workspace, bundled(root)))
    return found


def _missing_version(path: str, component: str) -> str:
    """The fix for a path missing from the manifest: the version its component last released,
    which only its tags record, so the message names them instead of guessing a version. The check
    doesn't read tags, since a clone may not have fetched them (missing-manifest-version design
    D1); it names the command that asks origin (D2)."""
    named = path if path == component else f"{path} ({component})"
    return (
        f'{named} has no version in {MANIFEST}: add "{path}" at the version it last released, its '
        f"latest {component}-v<version> tag (`git ls-remote --tags --sort=-v:refname origin "
        f"'{component}-v*'`), or at \"0.0.0\" if it has none."
    )


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
    if name == BUNDLE:
        for page in TAGGED_PAGES:
            update = page_update(page)
            if update not in entry.get("extra-files", []):
                found.append(
                    f"{path} ({name}) doesn't move the tag {page}'s install command names: add "
                    f"{json.dumps(update)} to its 'extra-files' in {CONFIG}."
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
    if entry.get("extra-files") != [RECORD_UPDATE]:
        found.append(
            f"{PROTOCOL}'s entry in {CONFIG} doesn't write the protocol version troupe records: "
            f"make its 'extra-files' [{json.dumps(RECORD_UPDATE)}]."
        )
    if PROTOCOL not in manifest:
        found.append(_missing_version(PROTOCOL, PROTOCOL))
    return found


def _record_problems(root: Path, manifest: dict[str, str]) -> list[str]:
    released = manifest.get(PROTOCOL)
    if released is None:
        return []  # _protocol_problems names the missing manifest entry
    should = f'{{"version": "{released}"}}, the protocol\'s version in {MANIFEST}'
    path = root / PROTOCOL_RECORD
    if not path.is_file():
        return [f"{PROTOCOL_RECORD} is missing: add it, holding {should}."]
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        record = None
    only_a_version = isinstance(record, dict) and set(record) == {"version"}
    version = record["version"] if only_a_version else None
    if not isinstance(version, str):
        return [f'{PROTOCOL_RECORD} must hold only {{"version": "<version>"}}: set it to {should}.']
    if version != released:
        return [
            f"{PROTOCOL_RECORD} records protocol {version}, but {MANIFEST} has "
            f"{released}: a protocol release pull request sets it. To correct it by hand, set it "
            f"to {released}."
        ]
    return []


def _group_problems(
    config: dict[str, Any], workspace: dict[str, str], shipped: set[str] | None
) -> list[str]:
    """Without a bundle (shipped is None) only packages/* members are expected, and no member is
    refused for not being shipped: bundle.py names the missing bundle (design D2)."""
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
    packages = {name for path, name in workspace.items() if path.startswith("packages/")}
    expected = packages | (shipped or set())
    found = [
        f"{component} isn't in the {LINKED_GROUP!r} linked group in {CONFIG}"
        + ("" if component in packages else f", but {BUNDLE} ships it")
        + ": add it to its 'components'."
        for component in sorted(expected - components)
    ]
    for component in sorted(components - expected):
        if component == PROTOCOL:
            found.append(
                f"{PROTOCOL} is in the {LINKED_GROUP!r} linked group in {CONFIG}, but it's "
                "released on its own: remove it from 'components'."
            )
        elif component not in workspace.values():
            found.append(
                f"{component} is in the {LINKED_GROUP!r} linked group in {CONFIG}, but it isn't a "
                "workspace member: remove it."
            )
        elif shipped is not None:
            found.append(
                f"{component} is in the {LINKED_GROUP!r} linked group in {CONFIG}, but {BUNDLE} "
                "doesn't ship it: remove it."
            )
    return found
