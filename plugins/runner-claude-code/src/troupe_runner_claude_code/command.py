"""Claude Code's command line, standard input and private files for one run (design D3, D4).

The command line holds only fixed flags, numbers, the checked model and the paths of the runner's
own private files. The direction goes on standard input; the character and the tool rules go in
files. So nothing from troupe or config is parsed by a shell on any platform (an npm ``claude.cmd``
runs through ``cmd.exe``), shows in a process listing, or meets Windows' command-line limit.
"""

import json
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from troupe_runner_claude_code.defaults import DEFAULT_MAX_BUDGET_USD
from troupe_runner_claude_code.options import Options

ENGINE_ENVIRONMENT = {
    "DISABLE_AUTOUPDATER": "1",
    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
}
"""Set for every run, so a run neither updates Claude Code nor sends its telemetry. Neither touches
the login."""

PRIVATE_PREFIX = "troupe-claude-code-"


@dataclass(frozen=True)
class Launch:
    """Everything needed to start Claude Code for one run."""

    argv: list[str]
    stdin: bytes
    env: dict[str, str]


class PrivateDirectoryError(Exception):
    """The private directory couldn't be made outside the workspace."""

    def __init__(self, where: str, problem: str) -> None:
        super().__init__(problem)
        self.where = where
        self.problem = problem


def make_private_directory(workspace: Path) -> Path:
    """A new directory for the run's private files, readable only by this user on POSIX, and
    never inside the workspace, where the effect check and the run's diff would see it."""
    try:
        private = Path(tempfile.mkdtemp(prefix=PRIVATE_PREFIX))
    except OSError as error:
        raise PrivateDirectoryError(
            tempfile.gettempdir(), f"The runner couldn't make its private directory: {error}"
        ) from error
    if private.resolve().is_relative_to(workspace.resolve()):
        private.rmdir()
        raise PrivateDirectoryError(
            str(private),
            "The temporary directory is inside the workspace, so the run's private files would "
            "be part of its work.",
        )
    return private


def budget_text(value: float) -> str:
    """``value`` as Claude Code reads it: the shortest text that round-trips, without ``.0``."""
    text = repr(float(value))
    return text.removesuffix(".0")


def build(
    claude: Path,
    options: Options,
    direction: str,
    character: str | None,
    private: Path,
    env: Mapping[str, str],
) -> Launch:
    """The launch for one run, writing its private files into ``private``."""
    argv = [
        str(claude),
        "-p",
        "--output-format",
        "stream-json",
        "--verbose",
        "--no-session-persistence",
        "--setting-sources",
        ",".join(options.setting_sources),
        "--strict-mcp-config",
        "--max-budget-usd",
        budget_text(
            options.max_budget_usd if options.max_budget_usd is not None else DEFAULT_MAX_BUDGET_USD
        ),
    ]
    if options.model is not None:
        argv += ["--model", options.model]
    if options.permission_mode is not None:
        argv += ["--permission-mode", options.permission_mode]
    if character is not None:
        path = private / "character.md"
        path.write_bytes(character.encode("utf-8"))
        argv += ["--append-system-prompt-file", str(path)]
    permissions: dict[str, list[str]] = {}
    if options.allowed_tools:
        permissions["allow"] = list(options.allowed_tools)
    if options.disallowed_tools:
        permissions["deny"] = list(options.disallowed_tools)
    if permissions:
        path = private / "settings.json"
        path.write_bytes(json.dumps({"permissions": permissions}, ensure_ascii=False).encode())
        argv += ["--settings", str(path)]
    return Launch(
        argv=argv,
        stdin=direction.encode("utf-8"),
        env={**env, **ENGINE_ENVIRONMENT},
    )


__all__ = [
    "ENGINE_ENVIRONMENT",
    "Launch",
    "PrivateDirectoryError",
    "budget_text",
    "build",
    "make_private_directory",
]
