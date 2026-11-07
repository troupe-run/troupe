"""Check every package a runner plugin depends on against troupe's list of licences (spec:
runner-protocol; runner-extras design D11, D13; owner, #333).

For each plugin under plugins/, it walks uv.lock from the plugin through its dependencies, skipping
workspace members: every package found is locked, so pinned. It reads each one's licence from its
installed metadata, in this environment, where the dev group installs every plugin and so every
runner's dependencies: License-Expression, else a License field that's a single SPDX id, else its
licence classifiers mapped to SPDX ids. A package that isn't installed, declares no licence, or has
one on neither tier of scripts/licences.toml fails.

A package in the weak-copyleft tier (MPL-2.0) is allowed only unmodified, as its own package: it
must be locked from a package index and not overridden in the root's [tool.uv.sources]. And no
tracked file under packages/, plugins/ or scripts/ may carry a weak-copyleft licence's notice, so
none of its files is copied in. A file pasted in with its notice removed isn't caught: removing
the notice is itself a breach, and review covers it (design D13).

It runs as a test, inside scripts/check.py. Standard library only, like check.py.
"""

import importlib.metadata
import re
import subprocess
import tomllib
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from release_config import members, normalise

LIST = "scripts/licences.toml"
LOCK = "uv.lock"
PLUGINS = "plugins/"
SCANNED = ("packages", "plugins", "scripts")
"""Where a copied weak-copyleft file would be troupe's source."""

CLASSIFIERS: Mapping[str, str] = {
    "License :: OSI Approved :: Apache Software License": "Apache-2.0",
    "License :: OSI Approved :: MIT License": "MIT",
    "License :: OSI Approved :: MIT No Attribution License (MIT-0)": "MIT-0",
    # Doesn't say which BSD licence; both are permissive, so either branch decides the tier.
    "License :: OSI Approved :: BSD License": "BSD-2-Clause OR BSD-3-Clause",
    "License :: OSI Approved :: ISC License (ISCL)": "ISC",
    "License :: OSI Approved :: Python Software Foundation License": "PSF-2.0",
    "License :: OSI Approved :: Mozilla Public License 2.0 (MPL 2.0)": "MPL-2.0",
}
"""Licence classifiers, for a package that declares no SPDX expression. One that isn't here isn't
guessed at: the package fails, and the mapping grows in a reviewed change."""

_SPDX_ID = re.compile(r"[A-Za-z0-9.+-]+")

Metadata = Mapping[str, list[str]]
"""A distribution's metadata fields, each with every value it has."""


@dataclass(frozen=True)
class Licences:
    """The list: the permissive licences, and each weak-copyleft one with the notice it carries."""

    permissive: frozenset[str]
    weak: Mapping[str, str]


def load_list(root: Path) -> Licences:
    data = tomllib.loads((root / LIST).read_text(encoding="utf-8"))
    weak = {name: str(entry["notice"]) for name, entry in data.get("weak-copyleft", {}).items()}
    return Licences(frozenset(data.get("permissive", {})), weak)


def installed_metadata(name: str) -> Metadata | None:
    """The installed distribution's licence fields, or None when it isn't installed."""
    try:
        found = importlib.metadata.metadata(name)
    except importlib.metadata.PackageNotFoundError:
        return None
    return {
        key: found.get_all(key) or [] for key in ("License-Expression", "License", "Classifier")
    }


def licence_of(meta: Metadata) -> str | None:
    """The SPDX expression a distribution declares, or None when it declares none this can read."""
    for expression in meta.get("License-Expression", []):
        if expression.strip():
            return expression.strip()
    for field in meta.get("License", []):
        if _SPDX_ID.fullmatch(field.strip()):
            return field.strip()
    mapped = [CLASSIFIERS[c] for c in meta.get("Classifier", []) if c in CLASSIFIERS]
    if mapped:
        return " OR ".join(mapped) if len(mapped) > 1 else mapped[0]
    return None


def tier(expression: str, licences: Licences) -> str | None:
    """'permissive', 'weak-copyleft' or None, for an SPDX expression of ORs of ANDs: the best tier
    any branch reaches, where a branch reaches the worst tier of its parts."""
    best: str | None = None
    for branch in expression.replace("(", " ").replace(")", " ").split(" OR "):
        parts = [part.strip() for part in branch.split(" AND ")]
        if any(" " in part or not part for part in parts):
            continue  # a WITH exception, or anything else this doesn't read: no tier
        if all(part in licences.permissive for part in parts):
            return "permissive"
        if all(part in licences.permissive or part in licences.weak for part in parts):
            best = "weak-copyleft"
    return best


def _lock(root: Path) -> dict[str, dict[str, Any]]:
    data = tomllib.loads((root / LOCK).read_text(encoding="utf-8"))
    return {normalise(str(p["name"])): p for p in data.get("package", [])}


def dependencies_of_runners(root: Path) -> dict[str, list[str]]:
    """Each runner plugin that depends on anything outside the workspace, with every such package
    it pulls in, directly or not, by name, in the order found."""
    workspace = {normalise(name): path for path, name in members(root).items()}
    locked = _lock(root)
    found: dict[str, list[str]] = {}
    for name, path in sorted(workspace.items(), key=lambda item: item[1]):
        if not path.startswith(PLUGINS):
            continue
        seen: list[str] = []
        queue = [name]
        visited = {name}
        while queue:
            package = locked.get(queue.pop(0), {})
            # A dependency on a package's extra brings that extra's requirements, which the lock
            # lists under the package's optional-dependencies.
            for dependency in package.get("dependencies", []):
                wanted = normalise(str(dependency["name"]))
                extras = dependency.get("extra", [])
                more = [
                    d
                    for e in extras
                    for d in locked.get(wanted, {}).get("optional-dependencies", {}).get(e, [])
                ]
                for item in [wanted, *(normalise(str(d["name"])) for d in more)]:
                    if item in visited:
                        continue
                    visited.add(item)
                    queue.append(item)
                    if item not in workspace:
                        seen.append(item)
        if seen:
            found[workspace_name(root, name)] = seen
    return found


def workspace_name(root: Path, normalised: str) -> str:
    return next(n for n in members(root).values() if normalise(n) == normalised)


def tracked(root: Path) -> list[str]:
    """The tracked files where a copied weak-copyleft file would be troupe's source."""
    done = subprocess.run(
        ["git", "ls-files", "-z", "--", *SCANNED],
        cwd=root,
        capture_output=True,
        check=True,
    )
    return [name for name in done.stdout.decode("utf-8").split("\0") if name]


def problems(
    root: Path,
    metadata: Callable[[str], Metadata | None] = installed_metadata,
    files: Iterable[str] | None = None,
) -> list[str]:
    """Every runner dependency whose licence isn't listed, or whose weak-copyleft use isn't
    unmodified, and every tracked file carrying a weak-copyleft notice."""
    licences = load_list(root)
    locked = _lock(root)
    root_project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    overridden = {
        normalise(n) for n in root_project.get("tool", {}).get("uv", {}).get("sources", {})
    }
    found: list[str] = []
    for runner, packages in dependencies_of_runners(root).items():
        for name in packages:
            who = f"{name}, which {runner} depends on,"
            meta = metadata(name)
            if meta is None:
                found.append(
                    f"{who} isn't installed, so its licence can't be read: run uv sync, which "
                    "installs every runner's dependencies."
                )
                continue
            expression = licence_of(meta)
            if expression is None:
                found.append(
                    f"{who} declares no licence in its metadata (License-Expression, License or a "
                    f"licence classifier): no licence was found, so it can't be checked against "
                    f"{LIST}. Replace it, or find its licence and raise it with the owner."
                )
                continue
            reached = tier(expression, licences)
            if reached is None:
                found.append(
                    f"{who} is licensed {expression}, which isn't on either tier of {LIST}: "
                    "replace the dependency, or, if the licence is compatible with Apache-2.0, add "
                    f"it to {LIST} in a reviewed change."
                )
            elif reached == "weak-copyleft":
                why = _not_unmodified(name, locked.get(name, {}), overridden)
                if why is not None:
                    found.append(
                        f"{who} is licensed {expression}, in the weak-copyleft tier of {LIST}, so "
                        "it's used only unmodified, installed from a package index as its own "
                        f"package, but {why}"
                    )
    for path in files if files is not None else tracked(root):
        if path == LIST or not path.startswith(tuple(f"{d}/" for d in SCANNED)):
            continue
        try:
            text = (root / path).read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for name, notice in licences.weak.items():
            if notice in text:
                found.append(
                    f"{path} carries the {name} notice: weak-copyleft code is used only as an "
                    "unmodified dependency, installed as its own package, never copied, vendored "
                    "or patched into troupe's source. Remove the file, and depend on its package."
                )
    return found


def _not_unmodified(
    name: str, package: Mapping[str, Any], overridden: Sequence[str] | set[str]
) -> str | None:
    """Why a weak-copyleft package might not be used unmodified, or None when it's locked from a
    package index and nothing overrides it."""
    if name in overridden:
        return "the root pyproject.toml's [tool.uv.sources] overrides it: remove the override."
    source = package.get("source", {})
    if "registry" not in source:
        kind = next(iter(source), "unknown")
        return f"uv.lock takes it from a {kind} source: lock it from the package index."
    return None
