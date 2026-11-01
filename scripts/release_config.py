"""Check that every workspace member is configured for release (spec: releases).

release-please only versions what its config lists, so a member left out would never release and
nothing would say so. This compares the config, the manifest and uv.lock with the workspace
members declared in the root pyproject.toml (release-automation design D10), and the protocol
version the troupe package records with the manifest's (protocol-own-release D3). Every package
versions on its own, so no components are linked, and the bundle names each one bare or pinned at
a release it has made (release-each-package design D1, D2, D8). It runs as a test,
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
REPOSITORY = "https://github.com/troupe-run/troupe"
"""Where the bundle's pins, and the documented install command, fetch troupe from."""
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
COMMIT_BATCH_SIZE = 100
"""Commits release-please reads per page of history, GraphQL's largest. A rebase-merged pull request
split across two pages gives its last commit every file the pull request changed, so the larger the
page, the rarer that is (changelog-commit-paths design D1; #223 decided this over fixing it)."""
COMMIT_SEARCH_DEPTH = 1000
"""How far back release-please reads, to the last release: past every commit on main before 0.1.0,
with room between later releases (changelog-commit-paths design D2)."""
CHANGELOG_SECTIONS: list[dict[str, Any]] = [
    {"type": "feat", "section": "Features"},
    {"type": "fix", "section": "Bug Fixes"},
    {"type": "perf", "section": "Performance Improvements"},
    {"type": "revert", "section": "Reverts"},
    {"type": "docs", "section": "Documentation", "hidden": True},
    {"type": "deps", "section": "Dependencies", "hidden": True},
    {"type": "style", "section": "Styles", "hidden": True},
    {"type": "chore", "section": "Miscellaneous Chores", "hidden": True},
    {"type": "refactor", "section": "Code Refactoring", "hidden": True},
    {"type": "test", "section": "Tests", "hidden": True},
    {"type": "build", "section": "Build System", "hidden": True},
    {"type": "ci", "section": "Continuous Integration", "hidden": True},
]
"""What changelogs show, as contributing/releasing.md says: a shown type is listed and releases; a
hidden one does neither, unless it's a breaking change (changelog-commit-paths design D3)."""
HISTORY_SETTINGS: dict[str, tuple[object, str]] = {
    "commit-batch-size": (
        COMMIT_BATCH_SIZE,
        "so a pull request's commits rarely fall on two pages of history (#223)",
    ),
    "commit-search-depth": (
        COMMIT_SEARCH_DEPTH,
        "so every commit since the last release reaches the changelogs",
    ),
    "changelog-sections": (
        CHANGELOG_SECTIONS,
        "so only feat, fix, perf, revert and breaking changes are listed, and only they release",
    ),
}
"""Each top-level setting that decides which commits reach which changelogs, and why, for the
check's messages (changelog-commit-paths design D4)."""
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


_PIN = re.compile(
    r"(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)\s*@\s*git\+(?P<url>[^@\s]+)@(?P<ref>[^#\s]+)"
    r"#subdirectory=(?P<subdirectory>\S+)"
)
_VERSION = re.compile(r"(\d+)\.(\d+)\.(\d+)")


def version_key(version: str) -> tuple[int, int, int]:
    """A release version, for comparing. Only the plain x.y.z that release-please makes."""
    matched = _VERSION.fullmatch(version)
    if matched is None:
        raise ValueError(f"not a release version: {version!r}")
    major, minor, patch = (int(part) for part in matched.groups())
    return major, minor, patch


def pin(name: str, version: str, path: str) -> str:
    """The bundle's dependency on the member at path, pinned at its release version (design D2)."""
    return f"{name} @ git+{REPOSITORY}@{name}-v{version}#subdirectory={path}"


def read_pin(requirement: str) -> tuple[str, str] | None:
    """The member and version a requirement pins at a release tag of this repository, whatever its
    subdirectory, or None when it isn't such a pin. For reading a tag's bundle, whose members this
    checkout may not have; pinned_version checks a pin against the workspace."""
    matched = _PIN.fullmatch(requirement.strip())
    if matched is None or matched["url"] != REPOSITORY:
        return None
    name = matched["name"]
    version = matched["ref"].removeprefix(f"{name}-v")
    if version == matched["ref"] or _VERSION.fullmatch(version) is None:
        return None
    return name, version


def pinned_version(requirement: str, name: str, path: str) -> str | None:
    """The version a requirement pins the member at path at, or None when it names it bare.
    Raises ValueError when it's neither: another repository, subdirectory or ref, a marker, extras
    or a version range."""
    if requirement.strip() == name:
        return None
    matched = _PIN.fullmatch(requirement.strip())
    if matched is None or matched["url"] != REPOSITORY or matched["subdirectory"] != path:
        raise ValueError(requirement)
    if normalise(matched["name"]) != normalise(name):
        raise ValueError(requirement)
    version = matched["ref"].removeprefix(f"{name}-v")
    if version == matched["ref"] or _VERSION.fullmatch(version) is None:
        raise ValueError(requirement)
    return version


def bundle_member(root: Path) -> str | None:
    """The bundle's directory among the workspace members, found by name, or None when it isn't
    one, which bundle.py reports. Not a literal path: see BUNDLE."""
    paths = [path for path, name in members(root).items() if name == BUNDLE]
    return paths[0] if paths else None


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
    found.extend(_linked_problems(config))
    bundle = bundle_member(root)
    if bundle is not None:
        found.extend(_pin_problems(root, bundle, workspace, manifest))
        found.extend(_bootstrap_problems(bundle, packages.get(bundle), manifest))
    found.extend(_prerelease_problems(config, packages))
    found.extend(_history_problems(config, packages))
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


def _prerelease_problems(config: dict[str, Any], packages: dict[str, dict[str, Any]]) -> list[str]:
    """Releases before 1.0 are pre-releases: set once at the top level, which every entry inherits,
    and which release-please applies only to 0.x versions (prerelease-before-1-0 design D1, D3)."""
    found: list[str] = []
    if "prerelease" not in config:
        found.append(
            f"{CONFIG} doesn't set 'prerelease': set it to true at the top level, so releases "
            "before 1.0 are pre-releases."
        )
    elif config["prerelease"] is not True:
        found.append(
            f"{CONFIG}'s 'prerelease' is {json.dumps(config['prerelease'])}: set it to true."
        )
    for path in sorted(packages):
        if "prerelease" in packages[path]:
            found.append(
                f"{path}'s entry in {CONFIG} sets 'prerelease': remove it, so it takes the "
                "top-level setting."
            )
    return found


def _history_problems(config: dict[str, Any], packages: dict[str, dict[str, Any]]) -> list[str]:
    """The settings that decide which commits reach which changelogs, each set once at the top level
    to exactly its value (changelog-commit-paths design D4). Compared as JSON, so "100" or 100.0 is
    another value, not the same one. Package entries can't hold the page size or depth (release-
    please's schema refuses them), but they can set their own sections."""
    found: list[str] = []
    for key, (want, why) in HISTORY_SETTINGS.items():
        if key not in config:
            found.append(
                f"{CONFIG} doesn't set '{key}': set it to {json.dumps(want)} at the top level, "
                f"{why}."
            )
        elif json.dumps(config[key], sort_keys=True) != json.dumps(want, sort_keys=True):
            found.append(
                f"{CONFIG}'s '{key}' is {json.dumps(config[key])}: set it to {json.dumps(want)}, "
                f"{why}."
            )
    for path in sorted(packages):
        if "changelog-sections" in packages[path]:
            found.append(
                f"{path}'s entry in {CONFIG} sets 'changelog-sections': remove it, so it takes the "
                "top-level setting."
            )
    return found


def _linked_problems(config: dict[str, Any]) -> list[str]:
    """Any linked-versions plugin: every package versions on its own (design D1)."""
    return [
        f"{CONFIG} links the components in {plugin.get('groupName')!r} ('linked-versions'): "
        "remove the plugin, since every package versions on its own (#218)."
        for plugin in config.get("plugins", [])
        if isinstance(plugin, dict) and plugin.get("type") == "linked-versions"
    ]


def _pin_problems(
    root: Path, bundle: str, workspace: dict[str, str], manifest: dict[str, str]
) -> list[str]:
    """Each of the bundle's dependencies on a member is bare, or pinned at a version the member
    has released (design D2, D8). Whether a pin is behind is the pinning step's business."""
    pyproject = f"{bundle}/pyproject.toml"
    project = tomllib.loads((root / pyproject).read_text(encoding="utf-8"))["project"]
    paths = {normalise(name): path for path, name in workspace.items()}
    found: list[str] = []
    for requirement in project.get("dependencies", []):
        path = paths.get(requirement_name(requirement))
        if path is None:
            continue
        name = workspace[path]
        released = manifest.get(path, "0.0.0")
        try:
            version = pinned_version(requirement, name, path)
        except ValueError:
            found.append(
                f"{name}'s dependency in {pyproject} is {requirement!r}: pin it as "
                f'"{pin(name, released, path)}", or name it bare.'
            )
            continue
        if version is None:
            continue
        if released == "0.0.0":
            found.append(
                f"{pyproject} pins {name} at {version}, but {MANIFEST} gives {path} 0.0.0: it "
                f'hasn\'t released, so name it bare ("{name}") until the pinning pull request '
                "pins it."
            )
        elif version_key(version) > version_key(released):
            found.append(
                f"{pyproject} pins {name} at {version}, but {MANIFEST} gives {path} {released}: "
                f"pin a version it has released, at most {released}."
            )
    return found


def _bootstrap_problems(
    bundle: str, entry: dict[str, Any] | None, manifest: dict[str, str]
) -> list[str]:
    """The bundle's commits are kept out of release pull requests only until its first pin, and
    only by excluding its own directory (design D7)."""
    if entry is None or "exclude-paths" not in entry:
        return []
    released = manifest.get(bundle, "0.0.0")
    if released != "0.0.0":
        return [
            f"{bundle}'s 'exclude-paths' in {CONFIG} is still set, but {MANIFEST} gives it "
            f"{released}: remove it, or {BUNDLE}'s commits never release."
        ]
    if entry["exclude-paths"] != [bundle]:
        return [
            f"{bundle}'s 'exclude-paths' in {CONFIG} is {json.dumps(entry['exclude-paths'])}: "
            f'make it ["{bundle}"], which keeps {BUNDLE} out of release pull requests until it\'s '
            "first pinned, or remove it."
        ]
    return []
