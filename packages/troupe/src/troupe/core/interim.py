"""Interim choices that config replaces (perform-status-logs design D4; config-model design D13).

An actor's config names its runner by name. This table is the only place a runner's name becomes a
command line, so no request or config file can carry a program to run, and it names the package
whose published schemas describe the runner's options, so config can check them without starting
the runner. When plugins are named and pinned in config (#38), this module is deleted.
"""

import sys
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import jsonschema

from troupe.core import schemas
from troupe.core.errors import TroupeError


@dataclass(frozen=True)
class Runner:
    """A runner troupe knows by name."""

    command: tuple[str, ...]
    """The command line that starts it."""

    package: str
    """The installed package whose ``schemas/`` holds its published schemas (spec: protocol)."""


RUNNERS: dict[str, Runner] = {
    "scripted": Runner(
        command=(sys.executable, "-m", "troupe_runner_scripted"),
        package="troupe_runner_scripted",
    ),
}
"""Each runner troupe knows, by name."""


def runner(name: str) -> Runner:
    """The runner named ``name``. Refused, naming the runners troupe knows, when there's none."""
    if name not in RUNNERS:
        known = ", ".join(sorted(RUNNERS))
        raise TroupeError(
            "runner.unknown",
            problem=f"troupe doesn't know a runner named {name!r} (it knows: {known}).",
            fix=f"Use one of: {known}. Until plugins are named in config (#38), these are the "
            "only runners troupe can start.",
            details={"runner": name, "known": sorted(RUNNERS)},
        )
    return RUNNERS[name]


def runner_command(name: str) -> Sequence[str]:
    """The command line that starts the runner named ``name``."""
    return runner(name).command


def options_schema(name: str) -> dict[str, Any]:
    """The options schema the runner named ``name`` publishes, read from the installed runner
    without starting it."""
    return schemas.plugin_schema(runner(name).package, "options.schema.json")


def options_validator(name: str) -> jsonschema.Draft202012Validator:
    """A validator for the runner named ``name``'s options, against its published options schema,
    which may refer to the runner contract's schemas by their ``$id``s."""
    runner_ = runner(name)
    uri = schemas.plugin_schema(runner_.package, "options.schema.json")["$id"]
    return schemas.validator(uri, runner_.package)
