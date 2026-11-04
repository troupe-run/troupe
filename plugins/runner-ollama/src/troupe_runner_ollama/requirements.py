"""What the runner requires of the platform, published as data and checked at preflight
(local-model-runner design D16; spec: ollama-runner, "The runner publishes its platform requirements
as data").

The requirements live in ``requirements.json`` beside the schemas, not in code, so the version the
runner needs is said in one place that anyone can read without running it. This is the interim form
until Decision #281 settles how components declare what they require and provide. A malformed entry
or a version the runner can't read is refused, never guessed at: a typo must not loosen the check.
"""

import json
import re
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Any

FIELDS = ("name", "minimum", "why")

_VERSION = re.compile(r"\A(\d+(?:\.\d+)*)(?:-([0-9A-Za-z.]+))?\Z")
"""Numbers separated by dots, with an optional suffix such as -rc1."""


class RequirementsError(Exception):
    """The published requirements are malformed: a bug in the package, not in the platform."""


@dataclass(frozen=True)
class Requirement:
    """One thing the runner requires, at least at ``minimum``."""

    name: str
    minimum: str
    why: str

    @property
    def wanted(self) -> str:
        return f">= {self.minimum}"


@dataclass(frozen=True)
class Unmet:
    """A requirement the platform doesn't meet, and what was found, when anything was."""

    requirement: Requirement
    found: str | None
    problem: str


def version_key(version: str) -> tuple[tuple[int, ...], bool, str] | None:
    """A key that orders versions part by part as numbers, a pre-release (``0.12.6-rc1``) before its
    release, or None when ``version`` isn't one the runner can read."""
    match = _VERSION.match(version.strip())
    if match is None:
        return None
    numbers = tuple(int(part) for part in match.group(1).split("."))
    while len(numbers) > 1 and numbers[-1] == 0:
        numbers = numbers[:-1]
    suffix = match.group(2) or ""
    return numbers, suffix == "", suffix


def _requirement(entry: object, index: int) -> Requirement:
    where = f"requires[{index}]"
    if not isinstance(entry, dict):
        raise RequirementsError(f"{where} isn't an object")
    unknown = sorted(set(entry) - set(FIELDS))
    if unknown:
        raise RequirementsError(f"{where} has fields the runner doesn't know: {', '.join(unknown)}")
    for field in FIELDS:
        if not isinstance(entry.get(field), str) or not entry[field]:
            raise RequirementsError(f"{where}.{field} is missing or isn't text")
    if version_key(entry["minimum"]) is None:
        raise RequirementsError(f"{where}.minimum {entry['minimum']!r} isn't a version")
    return Requirement(entry["name"], entry["minimum"], entry["why"])


def parse(data: Any) -> tuple[Requirement, ...]:  # noqa: ANN401 - JSON
    """The requirements in ``data``, the published file's JSON. Raises RequirementsError."""
    if (
        not isinstance(data, dict)
        or set(data) != {"requires"}
        or not isinstance(data["requires"], list)
    ):
        raise RequirementsError('the file must be an object holding only a "requires" list')
    return tuple(_requirement(entry, index) for index, entry in enumerate(data["requires"]))


def load(path: Path | None = None) -> tuple[Requirement, ...]:
    """The published requirements: ``path``, or the package's own ``requirements.json``."""
    text = (
        path.read_text(encoding="utf-8")
        if path is not None
        else files("troupe_runner_ollama").joinpath("requirements.json").read_text(encoding="utf-8")
    )
    return parse(json.loads(text))


def check(requirement: Requirement, found: str | None) -> Unmet | None:
    """Whether ``found``, the version the platform reported, meets ``requirement``: None when it
    does, otherwise what's unmet. A version that can't be read doesn't meet it."""
    if found is None:
        return Unmet(requirement, None, f"{requirement.name} didn't report its version")
    key = version_key(found)
    if key is None:
        return Unmet(
            requirement, found, f"{requirement.name} reported a version the runner can't read"
        )
    minimum = version_key(requirement.minimum)
    if minimum is None:  # parse refuses a minimum it can't read, so only a hand-made Requirement
        raise RequirementsError(
            f"{requirement.name}'s minimum {requirement.minimum!r} isn't a version"
        )
    if key < minimum:
        return Unmet(
            requirement, found, f"{requirement.name} {found} is older than {requirement.minimum}"
        )
    return None
