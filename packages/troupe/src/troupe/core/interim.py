"""Interim choices that config replaces (perform-status-logs design D4; config-model design D13).

An actor's config names its runner by name. This table is the only place a runner's name becomes a
command line, so no request or config file can carry a program to run, and it names the package
whose published schemas describe the runner's options, so config can check them without starting
the runner. When plugins are named and pinned in config (#38), this module is deleted.
"""

import importlib.util
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

import jsonschema

from troupe.core import schemas
from troupe.core.errors import TroupeError
from troupe.core.schemas import INSTALL_PAGE
from troupe.platform.processes import EnvironmentPolicy


@dataclass(frozen=True)
class RuntimeFit:
    """What runtime a runner can use, judged from the runtime's fields alone, so config can refuse
    a pair the runner would refuse at run time (spec: runtimes, "An actor's runtime fits its
    runner"; runtime-checks design D1). A test holds each to the runner's own check."""

    credential: bool = True
    """Whether it sends a runtime's credential. One that doesn't can't use a runtime with one."""

    path: Literal["any", "none", "required"] = "any"
    """What the runtime's endpoint's path must be: none (the runner adds its own API's path),
    one (such as /v1, which the runner's requests go below), or either. A lone / is no path."""


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

    runtime: Literal["required", "optional", "none"] = "none"
    """Whether its actors name a runtime: the service it talks to (spec: runtimes; runtimes design
    D4). Config refuses an actor whose runtime doesn't fit."""

    in_extra: bool = False
    """Whether it's installed through troupe-run's extra named exactly after it, rather than the
    base install: true for a runner whose plugin depends on more than the plugin SDK (spec: runs,
    installation; runner-extras design D1, D5). scripts/bundle.py checks it against troupe-run's
    pyproject.toml."""

    fit: RuntimeFit = RuntimeFit()
    """What runtime it can use, for a runner that takes one (runtime-checks design D1)."""


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


OPENAI_ENVIRONMENT: tuple[str, ...] = (
    # Networks behind a proxy.
    "HTTPS_PROXY",
    "HTTP_PROXY",
    "NO_PROXY",
    "https_proxy",
    "http_proxy",
    "no_proxy",
    # Certificates a service's TLS is signed with, where Python's own store doesn't have them.
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
)
"""What the OpenAI runner needs to reach a service, and nothing more: no credential, which
reaches it only as TROUPE_RUNTIME_CREDENTIAL, from its runtime (openai-style-runner design D14)."""


RUNNERS: dict[str, Runner] = {
    "claude-code": Runner(
        command=(sys.executable, "-m", "troupe_runner_claude_code"),
        package="troupe_runner_claude_code",
        environment=CLAUDE_CODE_ENVIRONMENT,
    ),
    "ollama": Runner(
        command=(sys.executable, "-m", "troupe_runner_ollama"),
        package="troupe_runner_ollama",
        # No variables: the runner reads none, not even OLLAMA_HOST. Its endpoint and model are
        # its runtime's, which reach it in run/start (ollama-uses-runtime design D1).
        runtime="required",
        # It sends no credential, and adds /api/... to an endpoint at the root (its design D3, D4).
        fit=RuntimeFit(credential=False, path="none"),
    ),
    "openai": Runner(
        command=(sys.executable, "-m", "troupe_runner_openai"),
        package="troupe_runner_openai",
        environment=OPENAI_ENVIRONMENT,
        runtime="required",
        # Its requests go below the endpoint, which an OpenAI-style service serves under a path
        # such as /v1 (runtime-checks design D5).
        fit=RuntimeFit(path="required"),
    ),
    "scripted": Runner(
        command=(sys.executable, "-m", "troupe_runner_scripted"),
        package="troupe_runner_scripted",
        runtime="optional",
    ),
}
"""Each runner troupe knows, by name."""


MOVED_TO_RUNTIME: dict[str, str] = {"ollama": "ollama"}
"""Runners whose ``model`` and ``endpoint`` options moved to a runtime, each with the built-in
runtime that replaces them. Config refuses an actor still holding them, with the config set that
moves them (spec: runtimes, "Options a runner moved to its runtime are refused with the move";
ollama-uses-runtime design D5)."""

MOVED_OPTIONS = ("endpoint", "model")
"""The options that moved, in path order."""


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


def installed(name: str) -> bool:
    """Whether the runner named ``name``, which troupe knows, has its package installed here, found
    without importing it (runner-extras design D6)."""
    return importlib.util.find_spec(runner(name).package) is not None


def installed_runner(name: str) -> Runner:
    """The runner named ``name``, refused with runner.unknown when troupe doesn't know it, and with
    runner.not-installed, naming the extra that installs it, when its package can't be found. Found
    without importing it (runner-extras design D6)."""
    entry = runner(name)
    if not installed(name):
        extra = name if entry.in_extra else None
        if extra is not None:
            fix = (
                f"Install troupe-run[{extra}] with the command at {INSTALL_PAGE}, in place of the "
                "command you installed troupe with. If you run troupe from a checkout of troupe, "
                "run uv sync there instead."
            )
        else:
            fix = (
                f"Reinstall troupe with the install command at {INSTALL_PAGE}. If you run troupe "
                "from a checkout of troupe, run uv sync there instead."
            )
        raise TroupeError(
            "runner.not-installed",
            problem=(
                f"The {name!r} runner isn't installed here (its package, {entry.package}, can't be "
                "found)" + (f": it comes with troupe-run[{extra}]." if extra is not None else ".")
            ),
            fix=fix,
            details={"runner": name, "package": entry.package}
            | ({"extra": extra} if extra is not None else {}),
        )
    return entry


def runner_command(name: str) -> Sequence[str]:
    """The command line that starts the runner named ``name``, refused when it isn't installed."""
    return installed_runner(name).command


def runner_environment(name: str, source: Mapping[str, str]) -> dict[str, str]:
    """The variables of ``source`` (perform's own environment) that the runner named ``name`` is
    given: those its table entry names and ``source`` sets, matched as the platform matches
    names, so case-insensitively on Windows."""
    policy = EnvironmentPolicy(names=frozenset(runner(name).environment))
    return {key: value for key, value in source.items() if policy.selects(key)}


def options_schema(name: str) -> dict[str, Any]:
    """The options schema the runner named ``name`` publishes, read from the installed runner
    without starting it."""
    return schemas.plugin_schema(installed_runner(name).package, "options.schema.json")


def options_validator(name: str) -> jsonschema.Draft202012Validator:
    """A validator for the runner named ``name``'s options, against its published options schema,
    which may refer to the runner contract's schemas by their ``$id``s."""
    runner_ = installed_runner(name)
    uri = schemas.plugin_schema(runner_.package, "options.schema.json")["$id"]
    return schemas.validator(uri, runner_.package)
