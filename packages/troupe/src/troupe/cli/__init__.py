"""The command-line surface: a thin client over troupe.core.

Parsing turns argv into a command and its arguments, or a structured usage error. Rendering turns
results and errors into text. No behaviour lives only here.
"""

import sys
from collections.abc import Sequence
from importlib.metadata import version
from typing import TextIO

from troupe.cli.commands import COMMANDS as RUN_COMMANDS
from troupe.cli.config import COMMANDS as CONFIG_COMMANDS
from troupe.cli.parser import Command, parse
from troupe.cli.render import render_error
from troupe.core.errors import BUG_REPORT_URL, TroupeError
from troupe.core.exit_codes import ExitCode
from troupe.core.schemas import protocol_version

COMMANDS: tuple[Command, ...] = (*RUN_COMMANDS, *CONFIG_COMMANDS)
"""The subcommands troupe offers."""


def run(
    argv: Sequence[str],
    *,
    commands: Sequence[Command] = COMMANDS,
    stdout: TextIO,
    stderr: TextIO,
) -> ExitCode:
    """Run one command line. Raises TroupeError for any failure the user should see."""
    parsed = parse(argv, commands)
    if parsed.show_version:
        print(f"troupe {version('troupe')} (protocol {protocol_version()})", file=stdout)
        return ExitCode.OK
    if parsed.command is None:
        print(parsed.help_text, end="", file=stdout)
        return ExitCode.OK
    return parsed.command.run(parsed.arguments, stdout, stderr)


def main(
    argv: Sequence[str] | None = None,
    *,
    commands: Sequence[Command] = COMMANDS,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> ExitCode:
    """Entry point for the ``troupe`` console script."""
    out = sys.stdout if stdout is None else stdout
    err = sys.stderr if stderr is None else stderr
    try:
        return run(
            sys.argv[1:] if argv is None else argv, commands=commands, stdout=out, stderr=err
        )
    except TroupeError as error:
        print(render_error(error), file=err)
        return error.exit_code
    except Exception as unexpected:  # the last line of defence must catch everything
        internal = TroupeError(
            "internal.unexpected",
            problem=f"troupe hit an unexpected error: {type(unexpected).__name__}: {unexpected}",
            fix=(
                "This is a bug in troupe. Please report it, with the command you ran, at "
                f"{BUG_REPORT_URL}"
            ),
        )
        print(render_error(internal), file=err)
        return internal.exit_code
