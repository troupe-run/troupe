"""Check that Dependabot proposes no version for a workspace member (spec: releases).

A member's version moves only through its own release. Dependabot reads every member as a
dependency and looks it up on PyPI, where `troupe` is someone else's project, and then asks uv to
lock the member at that version, which can't resolve (#254). So troupe's uv entry in the delivered
.github/dependabot.yml must ignore every member, for every version. The ignores are declared in
troupe-run/infrastructure (#259); this check, run as a test inside scripts/check.py, fails when a
member isn't covered (dependabot-uv-resolve design D3 to D5).

Names compare as packaging compares them (PEP 503), and `*` is Dependabot's only wildcard.
"""

import re
from pathlib import Path
from typing import Any

import yaml

from release_config import members, normalise

CONFIG = ".github/dependabot.yml"
FIX = (
    "add it to troupe's uv ignores in troupe-run/infrastructure's Dependabot policy "
    "(tofu/dependabot.json), which delivers this file"
)
NO_UV_ENTRY = f"{CONFIG}: no uv update entry for directory '/', so no member is ignored; {FIX}"
LIMITS = ("versions", "update-types")


def uncovered(name: str, path: str) -> str:
    return (
        f"{name} ({path}): no ignore in {CONFIG}'s uv entry covers every version of it, so "
        f"Dependabot would propose versions for it from PyPI; {FIX}"
    )


def pattern(name: str) -> re.Pattern[str]:
    """A Dependabot dependency-name as a pattern over normalised names: `*` matches any run of
    characters, and every other character is literal."""
    parts = (re.escape(part) for part in normalise(name).split("*"))
    return re.compile(".*".join(parts))


def uv_entry(config: object) -> dict[str, Any] | None:
    if not isinstance(config, dict) or not isinstance(config.get("updates"), list):
        return None
    for update in config["updates"]:
        if (
            isinstance(update, dict)
            and update.get("package-ecosystem") == "uv"
            and update.get("directory") == "/"
        ):
            return update
    return None


def ignores(entry: dict[str, Any]) -> tuple[list[re.Pattern[str]], list[str]]:
    """The patterns of the entry's ignores that cover every version, and a problem for each
    malformed ignore."""
    found: list[re.Pattern[str]] = []
    problems: list[str] = []
    listed = entry.get("ignore", [])
    if not isinstance(listed, list):
        return [], [f"{CONFIG}: the uv entry's ignore isn't a list ({listed!r}); {FIX}"]
    for ignore in listed:
        name = ignore.get("dependency-name") if isinstance(ignore, dict) else None
        if not isinstance(name, str):
            problems.append(
                f"{CONFIG}: the uv entry's ignore {ignore!r} has no dependency-name; {FIX}"
            )
        elif not any(limit in ignore for limit in LIMITS):
            found.append(pattern(name))
    return found, problems


def problems(root: Path) -> list[str]:
    file = root / CONFIG
    if not file.is_file():
        return [f"{CONFIG}: missing, {FIX}"]
    try:
        config = yaml.safe_load(file.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        return [f"{CONFIG}: not valid YAML ({error}); {FIX}"]
    entry = uv_entry(config)
    if entry is None:
        return [NO_UV_ENTRY]
    patterns, malformed = ignores(entry)
    if malformed:
        return malformed
    return [
        uncovered(name, path)
        for path, name in sorted(members(root).items(), key=lambda item: item[1])
        if not any(p.fullmatch(normalise(name)) for p in patterns)
    ]
