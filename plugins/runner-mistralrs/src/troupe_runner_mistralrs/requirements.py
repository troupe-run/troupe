"""The engine version the runner was built for, published as data and checked before a run is
acknowledged (spec: mistralrs-runner, "The runner checks its engine's version against published
data"; in-process-runner design D9).

The version lives in ``requirements.json`` beside the schemas, not in code, so it's said in one
place anyone can read. The check is exact: the runner maps the engine's own words for a full context
and for Metal kernels that don't compile, which another version may word differently. A malformed
entry is refused, never guessed at: a typo must not loosen the check.
"""

import json
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from importlib.resources import files
from typing import Any

FIELDS = ("name", "version", "why")


class RequirementsError(Exception):
    """The published requirements are malformed: a bug in the package, not in the platform."""


@dataclass(frozen=True)
class Requirement:
    """One package the runner requires at exactly ``version``."""

    name: str
    version: str
    why: str


@dataclass(frozen=True)
class Unmet:
    """Why a requirement isn't met: the version found, or None when the package isn't there."""

    requirement: Requirement
    found: str | None


def parse(data: Any) -> list[Requirement]:  # noqa: ANN401 - JSON
    """The requirements in ``data``, a parsed requirements.json. Raises RequirementsError."""
    if not isinstance(data, dict) or set(data) != {"requires"}:
        raise RequirementsError("requirements.json must be an object holding only 'requires'")
    entries = data["requires"]
    if not isinstance(entries, list) or not entries:
        raise RequirementsError("'requires' must be a list of at least one requirement")
    found: list[Requirement] = []
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != set(FIELDS):
            raise RequirementsError(f"each requirement holds exactly {', '.join(FIELDS)}")
        if not all(isinstance(entry[key], str) and entry[key] for key in FIELDS):
            raise RequirementsError("each requirement's fields are non-empty text")
        found.append(Requirement(entry["name"], entry["version"], entry["why"]))
    return found


def load() -> list[Requirement]:
    """The requirements this package publishes."""
    text = files("troupe_runner_mistralrs").joinpath("requirements.json").read_text("utf-8")
    return parse(json.loads(text))


def installed(name: str) -> str | None:
    """The installed version of the package ``name``, or None when it isn't installed."""
    try:
        return version(name)
    except PackageNotFoundError:
        return None


def unmet(requirements: list[Requirement], found: dict[str, str | None]) -> Unmet | None:
    """The first requirement ``found`` (each package's installed version) doesn't meet, or None."""
    for requirement in requirements:
        have = found.get(requirement.name)
        if have != requirement.version:
            return Unmet(requirement, have)
    return None
