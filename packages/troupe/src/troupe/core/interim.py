"""Interim choices that config replaces (perform-status-logs design D4; config-model design D13).

An actor's config names its runner by name. This table is the only place a runner's name becomes a
command line, so no request or config file can carry a program to run, and it names the package
whose published schemas describe the runner's options, so config can check them without starting
the runner. When plugins are named and pinned in config (#38), this module is deleted.
"""

import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import jsonschema

from troupe.core import schemas
from troupe.core.errors import TroupeError
from troupe.platform.processes import EnvironmentPolicy


@dataclass(frozen=True)
class Runner:
    """A runner troupe knows by name."""

    command: tuple[str, ...]
    """The command line that starts it."""

    package: str
    """The installed package whose ``schemas/`` holds its published schemas (spec: protocol)."""

    environment: tuple[str, ...] = ()
    """The variables perform copies from its own environment into the runner's, each only when
    set there (claude-code-runner design D8). Nothing else reaches the runner."""


CLAUDE_CODE_ENVIRONMENT: tuple[str, ...] = (
    # Find claude, and run its tools.
    "PATH",
    "PATHEXT",
    "COMSPEC",
    # Find the person's login and Claude Code's config.
    "HOME",
    "USER",
    "LOGNAME",
    "USERPROFILE",
    "HOMEDRIVE",
    "HOMEPATH",
    "USERNAME",
    "APPDATA",
    "LOCALAPPDATA",
    "XDG_CONFIG_HOME",
    "XDG_DATA_HOME",
    "XDG_CACHE_HOME",
    "XDG_RUNTIME_DIR",
    "CLAUDE_CONFIG_DIR",
    # The credentials #55 names.
    "CLAUDE_CODE_OAUTH_TOKEN",
    "ANTHROPIC_API_KEY",
    # Temporary files.
    "TMPDIR",
    "TEMP",
    "TMP",
    # Text and locale.
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    # Networks behind a proxy.
    "HTTPS_PROXY",
    "HTTP_PROXY",
    "NO_PROXY",
    "https_proxy",
    "http_proxy",
    "no_proxy",
    "NODE_EXTRA_CA_CERTS",
)
"""What Claude Code needs to run and to find the person's login, and nothing more: the host starts a
runner with only what it is given (claude-code-runner design D8)."""


RUNNERS: dict[str, Runner] = {
    "claude-code": Runner(
        command=(sys.executable, "-m", "troupe_runner_claude_code"),
        package="troupe_runner_claude_code",
        environment=CLAUDE_CODE_ENVIRONMENT,
    ),
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


def runner_environment(name: str, source: Mapping[str, str]) -> dict[str, str]:
    """The variables of ``source`` (perform's own environment) that the runner named ``name`` is
    given: those its table entry names and ``source`` sets, matched as the platform matches
    names, so case-insensitively on Windows."""
    policy = EnvironmentPolicy(names=frozenset(runner(name).environment))
    return {key: value for key, value in source.items() if policy.selects(key)}


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
