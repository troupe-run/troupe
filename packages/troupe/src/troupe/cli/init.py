"""troupe init on the command line (spec: cli; init-and-audition design D1, D4, D8, D9).

It builds the request as data and calls the core's ``init`` through the dispatcher, in a session
whose theatre is the working directory: there's no theatre to find yet, and the core checks for
one here or above. It then phrases the result's steps as commands to copy, for this platform.
"""

import argparse
import os
import shlex
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO

from troupe.cli.commands import _call, _ignore_cancel, _notices
from troupe.cli.parser import Command
from troupe.cli.render import render_notice
from troupe.core.client.session import CancelSignal, Session
from troupe.core.config_paths import shown
from troupe.core.defaults import RUNTIMES
from troupe.core.errors import TroupeError
from troupe.core.exit_codes import ExitCode
from troupe.core.runtimes import VARIABLE_PATTERN, env_name
from troupe.core.schemas import INSTALL_PAGE
from troupe.core.theatre import THEATRE_DIR

COMMAND = "troupe init"
COMMIT_MESSAGE = "Add a troupe theatre"
"""The message the printed commit step suggests."""


def _configure(parser: argparse.ArgumentParser) -> None:
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


def _missing_audition() -> TroupeError:
    """--runner without --audition: the parser has no "requires" shape (design D4)."""
    return TroupeError(
        "usage.missing-argument",
        problem=f"{COMMAND}: --runner names the example actor's runner, so it needs --audition.",
        fix=f"Add --audition, or leave out --runner. Run `{COMMAND} --help` to see the options.",
        details={"command": COMMAND, "argument": "--audition"},
    )


def _show_notice(update: dict[str, Any], stderr: TextIO) -> None:
    if update.get("kind") == "notice":
        print(render_notice(update["notice"]), file=stderr, flush=True)


@dataclass(frozen=True)
class Shell:
    """How the allow step is phrased for one family of shells: the line that sets a variable, and
    where to keep it so every new shell has it (#235: once, in the shell profile)."""

    line: str
    """The line, with ``{variable}`` and ``{value}`` to fill in."""
    profile: str
    """The profile the note names."""

    def allow_line(self, variable: str, value: str) -> str:
        return self.line.format(variable=variable, value=value)


POSIX = Shell("export {variable}={value}", "~/.zshrc or ~/.bashrc")
POWERSHELL = Shell('$env:{variable} = "{value}"', "your PowerShell profile ($PROFILE)")
SHELL = POWERSHELL if sys.platform == "win32" else POSIX
"""The shell the printed steps are phrased for: one choice, so the line and its note agree."""


def _step_lines(step: dict[str, Any]) -> list[str]:
    """The commands one step asks for, ready to copy."""
    kind = step["kind"]
    if kind == "commit":
        return [
            shlex.join(["git", "add", *step["paths"]]),
            shlex.join(["git", "commit", "-m", COMMIT_MESSAGE]),
        ]
    if kind == "allow-local-stage":
        return [SHELL.allow_line(step["variable"], step["value"])]
    return [shlex.join(["troupe", "perform", step["actor"], "--direction", step["direction"]])]


def _option(entries: list[dict[str, Any]], actor: str, name: str) -> object:
    """The value the audition's change set for ``actors.<actor>.options.<name>``, or None."""
    for entry in entries:
        if entry.get("path") == ["actors", actor, "options", name]:
            return entry.get("after")
    return None


def _value(entries: list[dict[str, Any]], actor: str, name: str) -> object:
    """The value the audition's change set for ``actors.<actor>.<name>``, or None."""
    for entry in entries:
        if entry.get("path") == ["actors", actor, name]:
            return entry.get("after")
    return None


def _key_note(runtime: object) -> str:
    """What to set for a built-in runtime's key: the variable it's read from, the person's
    ``TROUPE_RUNTIME_<NAME>_CREDENTIAL_ENV`` when it's set, else the built-in's; empty when it has
    none. An override that isn't a variable's name is named but never shown, since it may hold the
    key itself. A fresh theatre's config names none of its own."""
    if isinstance(runtime, str):
        override = env_name(runtime, "credential_env")
        chosen = os.environ.get(override)
        if chosen and not VARIABLE_PATTERN.match(chosen):
            return (
                f"{override} isn't the name of a variable, so a run will be refused: set it to the "
                "name of the variable that holds your key, not the key, or unset it. "
            )
        if chosen:
            return f"Set {chosen} to your API key for the {runtime} runtime. "
    variable = _key_variable(runtime)
    return f"Set {variable} to your API key for the {runtime} runtime. " if variable else ""


def _key_variable(runtime: object) -> str | None:
    """The variable a built-in runtime's key is read from, or None when it has none."""
    built_in = RUNTIMES.get(runtime) if isinstance(runtime, str) else None
    credential = None if built_in is None else built_in.get("credential")
    env = credential.get("env") if isinstance(credential, dict) else None
    return env if isinstance(env, str) else None


def _step_notes(step: dict[str, Any], entries: list[dict[str, Any]]) -> list[str]:
    """What a person should know about one step, after its commands. ``entries`` are the audition's
    config changes, which say what the step's actor runs with."""
    kind = step["kind"]
    if kind == "commit":
        return ["A run works from your latest commit, so commit the theatre first."]
    if kind == "allow-local-stage":
        return [
            "troupe runs an actor on your machine only when policy allows it. Run this line now, "
            f"and add it once to {SHELL.profile}: it then applies to every theatre you run."
        ]
    notes = []
    if step["runner"] == "claude-code":
        notes.append("Claude Code must be installed and logged in.")
    if step["runner"] == "ollama":
        model = _value(entries, step["actor"], "model")
        notes.append(
            f"Ollama must be running, with its model pulled: ollama pull {model}"
            if isinstance(model, str)
            else "Ollama must be running, with the actor's model pulled."
        )
    if step["runner"] == "openai":
        runtime = _value(entries, step["actor"], "runtime")
        tokens = _option(entries, step["actor"], "maxTotalTokens")
        notes.append(
            _key_note(runtime)
            + "A run costs money"
            + (
                f", and stops once it has used the actor's budget of {tokens:,} tokens."
                if isinstance(tokens, int)
                else "."
            )
        )
    if step.get("extra"):
        notes.append(
            f"The {step['runner']} runner comes with troupe-run[{step['extra']}]: whoever runs "
            f"this theatre elsewhere installs it with the command at {INSTALL_PAGE}."
        )
    notes.append(
        "The run works in its own worktree: see what it did with troupe diff, and keep it with "
        "troupe accept."
    )
    return notes


def render_init(result: dict[str, Any], directory: Path, stdout: TextIO) -> None:
    rehearsed = result["rehearsed"]
    would = "Would make" if rehearsed else "Made"
    print(f"{would} a theatre in {directory}: {THEATRE_DIR}/", file=stdout)
    for file in result["files"]:
        print(f"  {'would write' if rehearsed else 'wrote'} {file['path']}", file=stdout)
    actor = result.get("actor")
    if actor is None:
        if not rehearsed:
            print(
                f"Next: commit {THEATRE_DIR}/, and define an actor with troupe config set, or run "
                f"{COMMAND} --audition in a new repository for a working example.",
                file=stdout,
            )
        return
    print(
        f"{'Would define' if rehearsed else 'Defined'} the actor {actor['name']}, with the "
        f"{actor['runner']} runner.",
        file=stdout,
    )
    character = f"{THEATRE_DIR}/actors/{actor['name']}.md"
    if any(file["path"] == character for file in result["files"]):
        # Not "edit it": troupe can't read hand edits back yet (#119), so an edited file makes the
        # next command refuse with config.file-not-troupes (first-run-walkthrough design D8).
        print(
            f"Its character, the prompt it runs with, is {character}. To change it, write yours "
            "in a file and run: troupe config set "
            f"{shown(('actors', actor['name'], 'character'))}=@<file>",
            file=stdout,
        )
    if rehearsed:
        print("Rehearsal: nothing was made, written or recorded.", file=stdout)
        return
    print("\nNext:", file=stdout)
    for number, step in enumerate(result["steps"], start=1):
        lines = _step_lines(step)
        print(f"{number}. {lines[0]}", file=stdout)
        for line in lines[1:]:
            print(f"   {line}", file=stdout)
        for note in _step_notes(step, result["entries"]):
            # A comment in sh and PowerShell alike, so the whole block can be copied as it is.
            print(f"   # {note}", file=stdout)


def _run(arguments: argparse.Namespace, stdout: TextIO, stderr: TextIO) -> ExitCode:
    if arguments.runner is not None and not arguments.audition:
        raise _missing_audition()
    params: dict[str, Any] = {}
    if arguments.audition:
        params["audition"] = {} if arguments.runner is None else {"runner": arguments.runner}
    if arguments.rehearse:
        params["rehearse"] = True
    directory = Path.cwd()
    session = Session(theatre=directory, env=dict(os.environ), cancel=CancelSignal())
    result = _call("init", params, session, lambda u: _show_notice(u, stderr), _ignore_cancel)
    _notices(result, stderr)
    render_init(result, directory, stdout)
    return ExitCode.WOULD_CHANGE if arguments.rehearse else ExitCode.OK


COMMANDS: tuple[Command, ...] = (
    Command(
        "init",
        "Make a theatre here, and with --audition, a working example actor.",
        _configure,
        _run,
    ),
)
