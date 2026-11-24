# /// script
# dependencies = []
# ///
"""Check that every recorded version's release notes match its changelog section (spec: releases;
release-notes-non-ascii design D1 to D6).

Usage: gh api --paginate repos/<owner>/<repo>/releases \\
           --jq '.[] | [.tag_name, .body, .draft] | @json' \\
           | python3 scripts/release_notes.py [--root DIR]
       python3 scripts/release_notes.py --section <tag> [--root DIR]

The release workflow runs this after release-please on every push to main. When a release pull
request's body overflows, release-please 17.6.0 saves it with Node's latin1 encoding, which keeps
each character's low byte, and reads it back as UTF-8: every ⚠ in 0.2.0's notes was published as
U+FFFD, and the run passed (#486). The changelog, written as UTF-8, kept its text. So each tag
`release_tags.expected()` names must have a release whose notes equal that version's section of the
component's CHANGELOG.md, apart from the date at the end of the heading.

Reads the releases on standard input, one JSON array `[tag, body, draft]` per line. Prints each
release that differs (the first line that differs, and how many U+FFFD its notes hold) and the
release guide's repair section, and exits 1. A tag with no published release, a changelog without
the version's section, or an input line that isn't such an array is an error that names the input
and exits 1. Exits 0 when every release matches.

With `--section <tag>`, prints that tag's changelog section instead: the notes to publish when
repairing it (design D6).

Standard library only, like release_tags.py.
"""

import argparse
import json
import re
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from release_config import CONFIG
from release_tags import UnreadableError, expected

REPAIR = "contributing/releasing.md#repairing-a-releases-notes"
"""The release guide's section on repairing a release's notes (design D6)."""
CHANGELOG = "CHANGELOG.md"
REPLACEMENT = "�"
"""What UTF-8 decoding puts in place of the lone low bytes release-please's overflow file holds."""
_TAG = re.compile(r"(?P<component>.+)-v(?P<version>\d+\.\d+\.\d+)")
_HEADING = re.compile(r"## \[?(?P<version>\d+\.\d+\.\d+)\]?(?:[ (]|$)")
_DATE = re.compile(r" \(\d{4}-\d{2}-\d{2}\)$")


@dataclass(frozen=True)
class Difference:
    """A release whose notes aren't its changelog section."""

    tag: str
    line: int
    changelog: str
    notes: str
    replacements: int


def _config(root: Path) -> dict[str, Any]:
    loaded = json.loads((root / CONFIG).read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise UnreadableError(f"{CONFIG} isn't a JSON object.")
    return loaded


def changelog_path(root: Path, tag: str) -> tuple[str, str]:
    """The changelog (relative to root) and the version a tag's notes come from."""
    match = _TAG.fullmatch(tag)
    if match is None:
        raise UnreadableError(f"'{tag}' isn't a tag of the form <component>-v<X.Y.Z>.")
    packages: dict[str, dict[str, Any]] = _config(root).get("packages", {})
    paths = [p for p, entry in packages.items() if entry.get("component") == match["component"]]
    if len(paths) != 1:
        raise UnreadableError(
            f"{CONFIG} names {len(paths)} packages with the component '{match['component']}' "
            f"of tag '{tag}', not one."
        )
    return f"{paths[0]}/{CHANGELOG}", match["version"]


def section(root: Path, tag: str) -> str:
    """The tag's version's section of its component's changelog: from its `## ` heading up to the
    next `## ` heading (design D4)."""
    name, version = changelog_path(root, tag)
    path = root / name
    if not path.is_file():
        raise UnreadableError(f"{name} doesn't exist, so '{tag}' has no changelog to compare with.")
    lines = path.read_bytes().decode("utf-8").replace("\r\n", "\n").split("\n")
    starts = [i for i, line in enumerate(lines) if line.startswith("## ")]
    for n, start in enumerate(starts):
        heading = _HEADING.match(lines[start])
        if heading is not None and heading["version"] == version:
            end = starts[n + 1] if n + 1 < len(starts) else len(lines)
            return "\n".join(lines[start:end]).strip() + "\n"
    raise UnreadableError(f"{name} has no section for {version}, so '{tag}' can't be compared.")


def _normal(text: str) -> list[str]:
    """The text as compared: LF line ends, no surrounding whitespace, no date on the heading."""
    lines = text.replace("\r\n", "\n").strip().split("\n")
    lines[0] = _DATE.sub("", lines[0])
    return lines


def compare(tag: str, changelog: str, notes: str) -> Difference | None:
    """How the notes differ from the changelog section, apart from the heading's date (D2)."""
    want, got = _normal(changelog), _normal(notes)
    if want == got:
        return None
    line = next(
        (i for i, (w, g) in enumerate(zip(want, got, strict=False)) if w != g),
        min(len(want), len(got)),
    )
    return Difference(
        tag=tag,
        line=line + 1,
        changelog=want[line] if line < len(want) else "(end of section)",
        notes=got[line] if line < len(got) else "(end of notes)",
        replacements=notes.count(REPLACEMENT),
    )


def read_releases(lines: Iterable[str]) -> dict[str, str]:
    """Each published (not draft) release's notes by tag, from the workflow's lines (design D1)."""
    published: dict[str, str] = {}
    seen: set[str] = set()
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as error:
            raise UnreadableError(f"input line {number} isn't JSON ({error.msg}).") from None
        if not (
            isinstance(item, list)
            and len(item) == 3
            and isinstance(item[0], str)
            and isinstance(item[1], str | None)
            and isinstance(item[2], bool)
        ):
            raise UnreadableError(
                f"input line {number} isn't a [tag, body, draft] array: {line.strip()[:80]}"
            )
        tag, body, draft = item
        if tag in seen:
            raise UnreadableError(f"input line {number} lists '{tag}' a second time.")
        seen.add(tag)
        if not draft:
            published[tag] = body or ""
    return published


def check(root: Path, lines: Iterable[str]) -> tuple[list[str], list[Difference]]:
    """The expected tags with no published release, and the releases whose notes differ."""
    published = read_releases(lines)
    unreleased: list[str] = []
    differences: list[Difference] = []
    for tag in expected(root):
        if tag not in published:
            unreleased.append(tag)
            continue
        difference = compare(tag, section(root, tag), published[tag])
        if difference is not None:
            differences.append(difference)
    return unreleased, differences


def report(unreleased: Sequence[str], differences: Sequence[Difference]) -> str:
    """What the failed run prints: each release, where it differs, and the repair route."""
    out = []
    if unreleased:
        out.append(
            "release notes: these tags have no published release, so there are no notes to "
            f"compare: {', '.join(unreleased)}."
        )
    for d in differences:
        replaced = (
            f" Its notes hold {d.replacements} U+FFFD, so text was lost in encoding"
            " (a release pull request whose body overflowed, #486)."
            if d.replacements
            else ""
        )
        out.append(
            f"release notes: {d.tag}'s notes differ from its changelog section at line {d.line}."
            f"{replaced}\n  changelog: {d.changelog}\n  notes:     {d.notes}"
        )
    out.append(f"Repair: {REPAIR}")
    return "\n".join(out)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--section", metavar="TAG", help="print TAG's changelog section and exit")
    args = parser.parse_args(argv)
    try:
        if args.section is not None:
            sys.stdout.buffer.write(section(args.root, args.section).encode("utf-8"))
            return 0
        stdin = sys.stdin.buffer.read().decode("utf-8")
        # split on LF only: str.splitlines() would also split at a U+2028 jq leaves in a body.
        unreleased, differences = check(args.root, stdin.split("\n"))
    except UnreadableError as error:
        print(f"release notes: {error}", file=sys.stderr)
        return 1
    if not unreleased and not differences:
        return 0
    sys.stderr.buffer.write((report(unreleased, differences) + "\n").encode("utf-8"))
    return 1


if __name__ == "__main__":
    sys.exit(main())
