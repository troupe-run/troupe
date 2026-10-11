"""Parse a command line into a command and its arguments, or a structured usage error.

Rules (spec: cli):
- Global flags are accepted anywhere, before or after the subcommand.
- A value that starts with ``-`` must come after ``--``. Without it, troupe refuses rather than
  guessing whether a value or an option was meant.
- Unknown commands and flags are usage errors that name what wasn't recognised and suggest the
  closest valid alternative.

argparse does the parsing (design D2). A pre-scan runs first, because argparse on its own accepts
some dash-leading values as positionals (``-5``) and reports unknown names as untyped messages.
"""

import argparse
import difflib
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import NoReturn, TextIO

from troupe.core.errors import TroupeError
from troupe.core.exit_codes import ExitCode

HELP_FIX = "Run `troupe --help` to see the commands and options."


@dataclass(frozen=True)
class Command:
    """A subcommand: its name, one line of help, how to declare its arguments, and how to run it."""

    name: str
    help: str
    configure: Callable[[argparse.ArgumentParser], None]
    run: Callable[[argparse.Namespace, TextIO], ExitCode]


@dataclass(frozen=True)
class Parsed:
    show_version: bool
    command: Command | None
    arguments: argparse.Namespace
    help_text: str


class _Parser(argparse.ArgumentParser):
    """An ArgumentParser that raises TroupeError instead of printing and exiting."""

    def error(self, message: str) -> NoReturn:
        raise TroupeError("usage.invalid", problem=f"{self.prog}: {message}", fix=HELP_FIX)


def _global_options() -> _Parser:
    options = _Parser(add_help=False)
    # SUPPRESS: a flag missing from the subcommand's part of the line must not reset one given
    # before the subcommand.
    options.add_argument(
        "--version", action="store_true", default=argparse.SUPPRESS, help="show the version"
    )
    options.add_argument(
        "-h", "--help", action="store_true", default=argparse.SUPPRESS, help="show this help"
    )
    return options


def _new_parser(prog: str, description: str, parents: list[_Parser]) -> _Parser:
    return _Parser(
        prog=prog,
        description=description,
        parents=parents,
        add_help=False,
        allow_abbrev=False,
        exit_on_error=False,
    )


def _options_of(parser: argparse.ArgumentParser) -> dict[str, argparse.Action]:
    # argparse keeps its option table private; this is the one place troupe reads it.
    return dict(parser._option_string_actions)


def _suggest(token: str, candidates: Sequence[str]) -> str | None:
    bare = {candidate.lstrip("-"): candidate for candidate in candidates}
    matches = difflib.get_close_matches(token.lstrip("-"), list(bare), n=1, cutoff=0.6)
    return bare[matches[0]] if matches else None


def _looks_like_a_flag(token: str) -> bool:
    return token.startswith("--") or (len(token) >= 2 and token[1].isalpha())


def _unknown_flag(token: str, known: Sequence[str]) -> TroupeError:
    suggestion = _suggest(token, known)
    hint = f"Did you mean `{suggestion}`? " if suggestion else f"{HELP_FIX} "
    return TroupeError(
        "usage.unknown-flag",
        problem=f"`{token}` is not a troupe option.",
        fix=f"{hint}If `{token}` is a value, put `--` before it.",
        details={"flag": token, "suggestion": suggestion},
    )


def _dash_value(token: str) -> TroupeError:
    return TroupeError(
        "usage.dash-value",
        problem=f"`{token}` starts with `-`, so it is read as an option, not a value.",
        fix=f"Put `--` before values that start with `-`, for example `-- {token}`.",
        details={"value": token},
    )


def _unknown_command(token: str, commands: Sequence[Command], flags: Sequence[str]) -> TroupeError:
    suggestion = _suggest(token, [command.name for command in commands] + list(flags))
    return TroupeError(
        "usage.unknown-command",
        problem=f"`{token}` is not a troupe command.",
        fix=f"Did you mean `{suggestion}`?" if suggestion else HELP_FIX,
        details={"command": token, "suggestion": suggestion},
    )


def _prescan(
    argv: Sequence[str],
    root: argparse.ArgumentParser,
    subparsers: dict[str, argparse.ArgumentParser],
    commands: Sequence[Command],
) -> tuple[str | None, set[str]]:
    """Refuse unknown commands, unknown flags and unseparated dash-leading values.

    Returns the chosen subcommand (if any) and the destinations of the options given.
    """
    known = _options_of(root)
    chosen: str | None = None
    given: set[str] = set()
    args = iter(argv)
    for arg in args:
        if arg == "--":
            break
        if arg.startswith("-"):
            name = arg.split("=", 1)[0] if arg.startswith("--") else arg
            action = known.get(name)
            if action is None:
                if _looks_like_a_flag(arg):
                    raise _unknown_flag(arg, sorted(known))
                raise _dash_value(arg)
            given.add(action.dest)
            if action.nargs != 0 and "=" not in arg:
                next(args, None)  # the option's value
            continue
        if chosen is None:
            if arg not in subparsers:
                raise _unknown_command(arg, commands, sorted(known))
            chosen = arg
            known = _options_of(subparsers[arg])
    return chosen, given


def parse(argv: Sequence[str], commands: Sequence[Command]) -> Parsed:
    """Parse ``argv`` against ``commands``. Raises TroupeError for any usage problem."""
    global_options = _global_options()
    root = _new_parser(
        "troupe",
        "Run your development process with agents and people in named roles.",
        [global_options],
    )
    subparsers: dict[str, argparse.ArgumentParser] = {}
    if commands:
        actions = root.add_subparsers(dest="command", metavar="<command>", parser_class=_Parser)
        for each in commands:
            sub = actions.add_parser(
                each.name,
                help=each.help,
                description=each.help,
                parents=[global_options],
                add_help=False,
                allow_abbrev=False,
                exit_on_error=False,
            )
            each.configure(sub)
            subparsers[each.name] = sub

    chosen, given = _prescan(argv, root, subparsers, commands)
    if given & {"help", "version"}:
        # Help and version answer before anything else, so they work on an incomplete command line.
        parser_for_help = subparsers[chosen] if chosen is not None else root
        return Parsed(
            show_version="version" in given,
            command=None,
            arguments=argparse.Namespace(),
            help_text=parser_for_help.format_help(),
        )
    try:
        arguments = root.parse_args(argv)
    except argparse.ArgumentError as error:
        raise TroupeError("usage.invalid", problem=f"troupe: {error}", fix=HELP_FIX) from error

    command = next((c for c in commands if c.name == chosen), None)
    return Parsed(
        show_version=False,
        command=command,
        arguments=arguments,
        help_text=root.format_help(),
    )
