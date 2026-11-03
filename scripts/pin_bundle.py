# /// script
# dependencies = []
# ///
"""Pin the bundle at each component's latest release (spec: releases; release-each-package D4, D5).

Usage: uv run scripts/pin_bundle.py --message PATH [--root DIR]

After release-please publishes releases, the release workflow runs this on main. For each workspace
member troupe-run depends on whose release in .release-please-manifest.json is above its pin (a
bare dependency counts as unpinned), it rewrites that one dependency to the member's release tag
(design D2). When that leaves no member bare, it also removes troupe-run's 'exclude-paths' from
release-please-config.json (design D7; refuse-bare-bundle-member D3), so the commit releases the
bundle. While a member that hasn't released stays bare, the exclusion stays, and the message says
so. Only those strings change: every other byte of both files stays as it was.

When something moves, it writes the commit message to PATH: breaking when a changelog section it now
pins has breaking changes, `feat` when one has features, otherwise `fix`, so the bundle's release is
the size of the largest change it ships (design D5). When nothing moves, it writes nothing. Either
way it exits 0; a malformed pin, a pin above the manifest or a changelog without a version it needs
exits 1, naming the file, and changes nothing.

The header above makes `uv run` treat this as a standalone script. Standard library only, like
check.py.
"""

import argparse
import json
import re
import sys
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from release_config import (
    BUNDLE,
    CONFIG,
    MANIFEST,
    bare,
    bundle_member,
    listed,
    members,
    normalise,
    pin,
    pinned_version,
    requirement_name,
    version_key,
)

ROOT = Path(__file__).resolve().parent.parent
BRANCH = "release-please--pin-bundle"
"""The pinning pull request's branch. Under release-please--, which troupe's ruleset lets only the
release App write, so the guard exempts it by name (design D6). release.yml holds a copy."""
SUBJECT_LIMIT = 72
"""GitHub cuts longer subjects, and the review flags them."""
BREAKING = "### ⚠ BREAKING CHANGES"
FEATURES = "### Features"
_HEADING = re.compile(r"^## \[?(\d+\.\d+\.\d+)\b", re.MULTILINE)
"""A release's heading as release-please writes it: `## 0.1.0 (date)` for a first release,
`## [0.1.1](compare-link) (date)` after that."""


class PinError(Exception):
    """Something the step can't pin past: the message names the file and the fix."""


@dataclass(frozen=True)
class Move:
    """One dependency of the bundle moving to a member's latest release."""

    name: str
    path: str
    requirement: str
    old: str | None
    new: str


def moves(root: Path) -> list[Move]:
    """Each of the bundle's dependencies that's behind its member's release, in file order."""
    bundle = _bundle(root)
    pyproject = f"{bundle}/pyproject.toml"
    project = tomllib.loads((root / pyproject).read_text(encoding="utf-8"))["project"]
    manifest: dict[str, str] = json.loads((root / MANIFEST).read_text(encoding="utf-8"))
    workspace = members(root)
    paths = {normalise(name): path for path, name in workspace.items()}
    found: list[Move] = []
    for requirement in project.get("dependencies", []):
        path = paths.get(requirement_name(requirement))
        if path is None or path == bundle:
            continue
        name = workspace[path]
        released = manifest.get(path, "0.0.0")
        try:
            old = pinned_version(requirement, name, path)
        except ValueError:
            raise PinError(
                f"{name}'s dependency in {pyproject} is {requirement!r}, which isn't a pin this "
                f'step can move: make it "{name}" or "{pin(name, released, path)}".'
            ) from None
        if old is not None and version_key(old) > version_key(released):
            raise PinError(
                f"{pyproject} pins {name} at {old}, but {MANIFEST} gives {path} {released}: "
                f"pin at most {released}."
            )
        if released != "0.0.0" and (old is None or version_key(old) < version_key(released)):
            found.append(Move(name, path, requirement, old, released))
    return found


def kind(root: Path, moved: Sequence[Move]) -> tuple[str, list[tuple[str, str]]]:
    """The commit's type, `feat` or `fix`, and each (component, version) with breaking changes,
    from the changelog sections above each old pin, up to its new one (design D5)."""
    feature = False
    breaking: list[tuple[str, str]] = []
    for move in moved:
        for version, text in _sections(root, move):
            feature = feature or _has(text, FEATURES)
            if _has(text, BREAKING):
                breaking.append((move.name, version))
    return ("feat" if feature else "fix"), sorted(breaking)


def message(root: Path, moved: Sequence[Move]) -> str:
    """The pinning commit's message, signed off as the release App (design D5)."""
    commit_type, breaking = kind(root, moved)
    mark = "!" if breaking else ""
    named = ", ".join(f"{move.name} {move.new}" for move in moved)
    subject = f"{commit_type}(bundle){mark}: ship {named}"
    if len(subject) > SUBJECT_LIMIT:
        subject = f"{commit_type}(bundle){mark}: ship {len(moved)} component releases"
    lines = [subject, "", f"Pin each component {BUNDLE} ships at its latest release:", ""]
    lines += [f"- {move.name}: {move.old or 'unpinned'} → {move.new}" for move in moved]
    if breaking:
        which = " and ".join(f"{name} {version}" for name, version in breaking)
        names = dict.fromkeys(name for name, _ in breaking)
        logs = " and ".join(f"{_path(moved, name)}/CHANGELOG.md" for name in names)
        verb = "has" if len(breaking) == 1 else "have"
        lines += ["", f"BREAKING CHANGE: {which} {verb} breaking changes: see {logs}."]
    still = left_bare(root, moved)
    if still:
        them = "them" if len(still) > 1 else "it"
        verb = "are" if len(still) > 1 else "is"
        their = "their" if len(still) > 1 else "its"
        lines += [
            "",
            f"{listed(still)} {verb} still bare, so {BUNDLE} doesn't release until a pinning pull "
            f"request pins {them}, after {their} first release (refuse-bare-bundle-member design "
            "D3).",
        ]
    signoff = json.loads((root / CONFIG).read_text(encoding="utf-8"))["signoff"]
    lines += ["", f"Signed-off-by: {signoff}"]
    return "\n".join(lines) + "\n"


def apply(root: Path, moved: Sequence[Move]) -> None:
    """Write each move into the bundle's pyproject.toml, and remove the bootstrap exclusion."""
    if not moved:
        return
    bundle = _bundle(root)
    pyproject = root / bundle / "pyproject.toml"
    text = pyproject.read_bytes().decode("utf-8")
    for move in moved:
        quoted = f'"{move.requirement}"'
        if text.count(quoted) != 1:
            raise PinError(
                f"{bundle}/pyproject.toml names {quoted} {text.count(quoted)} times: name it once."
            )
        text = text.replace(quoted, f'"{pin(move.name, move.new, move.path)}"')
    config_text = None if left_bare(root, moved) else _unexcluded(root, bundle)
    pyproject.write_bytes(text.encode("utf-8"))
    if config_text is not None:
        (root / CONFIG).write_bytes(config_text.encode("utf-8"))


def left_bare(root: Path, moved: Sequence[Move]) -> list[str]:
    """The members the bundle still names bare once moved is applied: each bare one the moves
    don't pin, which is one that hasn't released (refuse-bare-bundle-member design D3)."""
    pinning = {move.name for move in moved}
    return [name for name in bare(root, _bundle(root)) if name not in pinning]


def _unexcluded(root: Path, bundle: str) -> str | None:
    """The config without the bundle's 'exclude-paths' line, or None when it has none."""
    text = (root / CONFIG).read_bytes().decode("utf-8")
    config: dict[str, Any] = json.loads(text)
    entry: dict[str, Any] = config["packages"][bundle]
    if "exclude-paths" not in entry:
        return None
    lines = [line for line in text.splitlines(keepends=True) if '"exclude-paths"' in line]
    after = text.replace(lines[0], "", 1) if len(lines) == 1 else text
    entry.pop("exclude-paths")
    if len(lines) != 1 or json.loads(after) != config:
        raise PinError(
            f"{CONFIG}: {bundle}'s 'exclude-paths' isn't one line of its own that can be removed "
            "alone: put it on its own line, before another key."
        )
    return after


def _bundle(root: Path) -> str:
    bundle = bundle_member(root)
    if bundle is None:
        raise PinError(f"{BUNDLE} isn't a workspace member, so there's nothing to pin.")
    return bundle


def _sections(root: Path, move: Move) -> list[tuple[str, str]]:
    """Each changelog section above the old pin, up to the new one, as (version, text)."""
    log = f"{move.path}/CHANGELOG.md"
    try:
        text = (root / log).read_text(encoding="utf-8")
    except FileNotFoundError:
        raise PinError(
            f"{log} doesn't exist: release-please writes it with each release."
        ) from None
    headings = list(_HEADING.finditer(text))
    sections = {
        found[1]: text[found.end() : headings[i + 1].start() if i + 1 < len(headings) else None]
        for i, found in enumerate(headings)
    }
    if move.new not in sections:
        raise PinError(
            f"{log} has no {move.new} section, but {MANIFEST} gives {move.path} {move.new}: "
            "the release that made it should have written one."
        )
    low = version_key(move.old) if move.old is not None else (-1, -1, -1)
    high = version_key(move.new)
    return [(v, t) for v, t in sections.items() if low < version_key(v) <= high]


def _has(section: str, heading: str) -> bool:
    return any(line.strip() == heading for line in section.splitlines())


def _path(moved: Sequence[Move], name: str) -> str:
    [path] = [move.path for move in moved if move.name == name]
    return path


def main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--message", required=True, type=Path, help="where to write the message")
    parser.add_argument("--root", type=Path, default=ROOT, help="the repository (default: this)")
    arguments = parser.parse_args(argv)
    root: Path = arguments.root
    try:
        moved = moves(root)
        if not moved:
            return 0
        text = message(root, moved)
        apply(root, moved)
    except PinError as error:
        print(f"pin_bundle: {error}", file=sys.stderr)
        return 1
    arguments.message.write_text(text, encoding="utf-8")
    for move in moved:
        print(f"{move.name} {move.old or 'unpinned'} → {move.new}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
