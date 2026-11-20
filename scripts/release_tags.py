# /// script
# dependencies = []
# ///
"""Check that every version the manifest records has its release tag (spec: releases;
release-missing-components design D1, D2).

Usage: gh api --paginate repos/<owner>/<repo>/git/matching-refs/tags --jq '.[].ref' \\
           | python3 scripts/release_tags.py [--root DIR]

The release workflow runs this after release-please on every push to main. The manifest moves only
through a merged release pull request, so each version in it, other than an unreleased 0.0.0, should
have its tag `<component>-v<version>`, the component as release-please-config.json names it. #263's
run skipped two components and still passed (#484); this is what notices.

Reads the tag refs (`refs/tags/<name>`, one per line) on standard input. Prints each missing tag and
the release guide's repair section, and exits 1. A manifest path the config doesn't configure, a
package without a `component`, tags without components, or a version that isn't X.Y.Z is an error
that names the input and exits 1, rather than a guessed tag. Exits 0 when every tag exists.

Standard library only, like pin_bundle.py.
"""

import argparse
import json
import re
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from release_config import CONFIG, MANIFEST

REPAIR = "contributing/releasing.md#repairing-a-missing-release"
"""The release guide's section on repairing a missing release (design D4)."""
UNRELEASED = "0.0.0"
"""A new member's manifest version until its first release (releasing.md, "Adding a package")."""
_VERSION = re.compile(r"\d+\.\d+\.\d+")
_TAG_REF = "refs/tags/"


class UnreadableError(Exception):
    """The config or manifest doesn't say which tag a version needs."""


def _load(root: Path, name: str) -> dict[str, Any]:
    loaded = json.loads((root / name).read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise UnreadableError(f"{name} isn't a JSON object.")
    return loaded


def expected(root: Path) -> list[str]:
    """Each tag the manifest's versions need, in manifest order."""
    config: dict[str, Any] = _load(root, CONFIG)
    manifest = _load(root, MANIFEST)
    if config.get("include-component-in-tag") is not True:
        raise UnreadableError(
            f"{CONFIG} doesn't set \"include-component-in-tag\": true, so its tags don't name "
            "their components and this check can't tell them apart."
        )
    packages: dict[str, dict[str, Any]] = config.get("packages", {})
    tags = []
    for path, version in manifest.items():
        entry = packages.get(path)
        if entry is None:
            raise UnreadableError(
                f"{MANIFEST} has '{path}', which {CONFIG} doesn't configure: add it to "
                '"packages" (releasing.md, "Adding a package").'
            )
        component = entry.get("component")
        if not isinstance(component, str) or not component:
            raise UnreadableError(
                f"{CONFIG}'s entry for '{path}' has no \"component\" to name its tag."
            )
        if not isinstance(version, str) or not _VERSION.fullmatch(version):
            raise UnreadableError(
                f"{MANIFEST}'s version for '{path}' is {json.dumps(version)}, not X.Y.Z."
            )
        if version != UNRELEASED:
            tags.append(f"{component}-v{version}")
    return tags


def missing(root: Path, refs: Iterable[str]) -> list[str]:
    """The tags the manifest needs that aren't among the refs."""
    present = {ref.strip()[len(_TAG_REF) :] for ref in refs if ref.strip().startswith(_TAG_REF)}
    return [tag for tag in expected(root) if tag not in present]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)
    try:
        gone = missing(args.root, sys.stdin.read().splitlines())
    except UnreadableError as error:
        print(f"release tags: {error}", file=sys.stderr)
        return 1
    if not gone:
        return 0
    print(
        f"release tags: {MANIFEST} records versions that were never tagged: {', '.join(gone)}. "
        f"The release run that should have made them skipped them. Repair: {REPAIR}",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
