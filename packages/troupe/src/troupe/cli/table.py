"""The command table: every command's name, help and arguments (spec: cli; cli-starts-fast design
D2).

Reading a command line needs only this, so it imports nothing heavy. A command's work lives in
its family's module (troupe.cli.commands, troupe.cli.config, troupe.cli.init), which ``run``
imports when that command runs: ``troupe --help`` or a usage error never loads schema checking,
YAML, the async runtime or the core's handlers. tests/test_cli_startup.py keeps it that way.
"""

import argparse
from typing import TextIO

from troupe.cli.parser import Command
from troupe.core.exit_codes import ExitCode

# init


def _configure_init(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--audition",
        action="store_true",
        help="also define a working example actor, lead (Claude Code unless --runner says)",
    )
    parser.add_argument(
        "--runner", help="the example actor's runner, such as scripted (only with --audition)"
    )
    parser.add_argument(
        "--rehearse",
        action="store_true",
        help="run every check and make nothing: show what would be made",
    )


def _run_init(arguments: argparse.Namespace, stdout: TextIO, stderr: TextIO) -> ExitCode:
    from troupe.cli import init  # loaded when the command runs (design D2)

    return init.run(arguments, stdout, stderr)


INIT_COMMANDS: tuple[Command, ...] = (
    Command(
        "init",
        "Make a theatre here, and with --audition, a working example actor.",
        _configure_init,
        _run_init,
    ),
)

# perform


def _configure_perform(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("actor", help="the actor's name, as config defines it")
    parser.add_argument("--direction", help="what the actor is asked to do in this run")
    parser.add_argument(
        "--rehearse",
        action="store_true",
        help="run every check and start nothing: show what would run",
    )


def _run_perform(arguments: argparse.Namespace, stdout: TextIO, stderr: TextIO) -> ExitCode:
    from troupe.cli import commands  # loaded when the command runs (design D2)

    return commands.run_perform(arguments, stdout, stderr)


# status and logs


def _configure_status(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("run", nargs="?", help="a run's id, or at least its first 8 characters")
    parser.add_argument("--limit", type=int, help="how many runs to list, newest first")
    parser.add_argument("--json", action="store_true", help="print the result as JSON")


def _run_status(arguments: argparse.Namespace, stdout: TextIO, stderr: TextIO) -> ExitCode:
    from troupe.cli import commands  # loaded when the command runs (design D2)

    return commands.run_status(arguments, stdout, stderr)


def _configure_logs(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("run", help="a run's id, or at least its first 8 characters")
    parser.add_argument(
        "--follow", action="store_true", help="wait for new events and notices until the run ends"
    )
    parser.add_argument("--json", action="store_true", help="print updates and the result as JSON")


def _run_logs(arguments: argparse.Namespace, stdout: TextIO, stderr: TextIO) -> ExitCode:
    from troupe.cli import commands  # loaded when the command runs (design D2)

    return commands.run_logs(arguments, stdout, stderr)


# diff, accept and discard


def _configure_diff(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("run", help="a run's id, or at least its first 8 characters")
    parser.add_argument("--json", action="store_true", help="print the result as JSON")


def _run_diff(arguments: argparse.Namespace, stdout: TextIO, stderr: TextIO) -> ExitCode:
    from troupe.cli import commands  # loaded when the command runs (design D2)

    return commands.run_diff(arguments, stdout, stderr)


def _configure_settle(parser: argparse.ArgumentParser, rehearse: str) -> None:
    parser.add_argument("run", help="a run's id, or at least its first 8 characters")
    parser.add_argument("--reason", help="why, recorded in the lineage")
    parser.add_argument("--rehearse", action="store_true", help=rehearse)


def _configure_accept(parser: argparse.ArgumentParser) -> None:
    _configure_settle(
        parser, "check that the changes apply cleanly and name the files, changing nothing"
    )


def _run_accept(arguments: argparse.Namespace, stdout: TextIO, stderr: TextIO) -> ExitCode:
    from troupe.cli import commands  # loaded when the command runs (design D2)

    return commands.run_accept(arguments, stdout, stderr)


def _configure_discard(parser: argparse.ArgumentParser) -> None:
    _configure_settle(parser, "name the worktree that would be removed, removing nothing")


DISCARD_HELP = (
    "Remove a worktree run's worktree, keeping nothing it wrote. It removes files, not git state: "
    "branches, tags, stashes, config, hooks or pushes the run made in git stay."
)


def _run_discard(arguments: argparse.Namespace, stdout: TextIO, stderr: TextIO) -> ExitCode:
    from troupe.cli import commands  # loaded when the command runs (design D2)

    return commands.run_discard(arguments, stdout, stderr)


RUN_COMMANDS: tuple[Command, ...] = (
    Command("perform", "Run one actor and record the run.", _configure_perform, _run_perform),
    Command("status", "Show the most recent runs, or one run.", _configure_status, _run_status),
    Command("logs", "Show a run's events and notices in order.", _configure_logs, _run_logs),
    Command("diff", "Show the changes a worktree run captured.", _configure_diff, _run_diff),
    Command(
        "accept",
        "Apply a worktree run's changes to your files, unstaged, all or nothing.",
        _configure_accept,
        _run_accept,
    ),
    Command("discard", DISCARD_HELP, _configure_discard, _run_discard),
)

# config set and config unset


def _configure_set(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "assignments",
        nargs="+",
        metavar="path=value",
        help="a value to set, such as actors.tester.runner=scripted; path=@file reads it "
        "from a file. A key that holds a dot goes in brackets: prices[gpt-4.1]",
    )
    parser.add_argument("--reason", help="why, recorded with the change")
    parser.add_argument(
        "--json", action="store_true", help="read every value as JSON, whatever its schema says"
    )
    parser.add_argument(
        "--rehearse",
        action="store_true",
        help="change nothing: show what would be recorded and written",
    )


def _run_set(arguments: argparse.Namespace, stdout: TextIO, stderr: TextIO) -> ExitCode:
    from troupe.cli import config  # loaded when the command runs (design D2)

    return config.run_set(arguments, stdout, stderr)


def _configure_unset(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "paths",
        nargs="+",
        metavar="path",
        help="a value or a group to remove, such as actors.tester. A key that holds a dot goes "
        "in brackets: prices[gpt-4.1]",
    )
    parser.add_argument("--reason", help="why, recorded with the change")
    parser.add_argument(
        "--rehearse",
        action="store_true",
        help="change nothing: show what would be recorded and written",
    )


def _run_unset(arguments: argparse.Namespace, stdout: TextIO, stderr: TextIO) -> ExitCode:
    from troupe.cli import config  # loaded when the command runs (design D2)

    return config.run_unset(arguments, stdout, stderr)


# config get


def _configure_get(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "path",
        nargs="?",
        metavar="path",
        help="a value or group, such as actors.tester. A key that holds a dot goes in brackets: "
        "prices[gpt-4.1]",
    )
    parser.add_argument("--json", action="store_true", help="print the result as JSON")
    parser.add_argument(
        "--resolved",
        action="store_true",
        help="show runtimes as troupe resolves them, from its built-in ones, config and your "
        "environment, each value with where it came from",
    )


def _run_get(arguments: argparse.Namespace, stdout: TextIO, stderr: TextIO) -> ExitCode:
    from troupe.cli import config  # loaded when the command runs (design D2)

    return config.run_get(arguments, stdout, stderr)


# flush


def _configure_flush(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--force",
        action="store_true",
        help="replace files troupe didn't write too, keeping a copy of each",
    )
    parser.add_argument(
        "--rehearse", action="store_true", help="change nothing: show what would be written"
    )


def _run_flush(arguments: argparse.Namespace, stdout: TextIO, stderr: TextIO) -> ExitCode:
    from troupe.cli import config  # loaded when the command runs (design D2)

    return config.run_flush(arguments, stdout, stderr)


CONFIG_COMMANDS: tuple[Command, ...] = (
    Command("config set", "Set config values, as one change.", _configure_set, _run_set),
    Command(
        "config unset",
        "Remove config values or groups, as one change.",
        _configure_unset,
        _run_unset,
    ),
    Command(
        "config get", "Show config, or the value or group at a path.", _configure_get, _run_get
    ),
    Command(
        "flush", "Make the config files exactly what config says.", _configure_flush, _run_flush
    ),
)

COMMANDS: tuple[Command, ...] = (*INIT_COMMANDS, *RUN_COMMANDS, *CONFIG_COMMANDS)
"""The subcommands troupe offers, in the order their help lists them."""
