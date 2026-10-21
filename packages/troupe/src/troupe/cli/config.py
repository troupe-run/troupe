"""config set, config unset, config get and flush on the command line (spec: cli, config;
config-model design D10).

Each builds its request as data and calls the core through the client protocol's dispatcher, then
renders the result: what changed on standard output, notices on standard error. Typing a value by
its schema is the CLI's job (troupe.cli.values), since the core's requests carry JSON.
"""

import argparse
import json
from typing import Any, TextIO

from troupe.cli.commands import _call, _ignore_cancel, _notices, _session
from troupe.cli.parser import Command
from troupe.cli.render import render_notice
from troupe.cli.values import split_path, value_of
from troupe.core.errors import TroupeError
from troupe.core.exit_codes import ExitCode


def _show_notice(update: dict[str, Any], stderr: TextIO) -> None:
    if update.get("kind") == "notice":
        print(render_notice(update["notice"]), file=stderr, flush=True)


def _entry_line(entry: dict[str, Any]) -> str:
    path = ".".join(entry["path"])
    if "after" not in entry:
        return f"unset {path}"
    return f"{'changed' if 'before' in entry else 'set'} {path}"


def _file_line(file: dict[str, Any], *, rehearse: bool = False) -> str:
    verb = {"write": "wrote", "remove": "removed", "finish": "finished", "discard": "discarded"}
    if rehearse:
        verb = {action: action for action in verb}
    line = f"{verb[file['action']]} {file['path']} ({file['reason']})"
    if "kept" in file:
        line += f"; what it held is kept as {file['kept']}"
    return line


# config set and config unset


def _configure_set(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "assignments",
        nargs="+",
        metavar="path=value",
        help="a value to set, such as actors.tester.runner=scripted; path=@file reads it "
        "from a file",
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


def _runner_of(actor: str, assignments: list[tuple[str, str]]) -> str | None:
    """The runner the actor will have: set in this command, or already in config."""
    for dotted, text in assignments:
        if dotted == f"actors.{actor}.runner" and not text.startswith("@"):
            return text
    result = _call(
        "config-get",
        {"path": ["actors", actor, "runner"]},
        _session(),
        lambda u: None,
        _ignore_cancel,
    )
    runner = result.get("value")
    return runner if isinstance(runner, str) else None


def _assignments(raw: list[str]) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for each in raw:
        dotted, equals, text = each.partition("=")
        if not equals:
            raise TroupeError(
                "config.invalid",
                problem=f"{each!r} doesn't set anything: a value is written <path>=<value>.",
                fix=f"Write it as {each}=<value>, or use troupe config unset {each} to remove it.",
                details={
                    "path": [k for k in dotted.split(".") if k] or [dotted],
                    "rule": "a value is written <path>=<value>",
                },
            )
        found.append((dotted, text))
    return found


def _render_change(result: dict[str, Any], stdout: TextIO, *, rehearse: bool) -> ExitCode:
    if not result["entries"]:
        print("Nothing changed: config already holds that.", file=stdout)
        return ExitCode.OK
    would = "would " if rehearse else ""
    for entry in result["entries"]:
        print(would + _entry_line(entry), file=stdout)
    for file in result["files"]:
        print(would + _file_line(file, rehearse=rehearse), file=stdout)
    if "change" in result:
        print(f"recorded change {result['change']}", file=stdout)
    if rehearse:
        print("Rehearsal: nothing was recorded or written.", file=stdout)
        return ExitCode.WOULD_CHANGE
    return ExitCode.OK


def _run_set(arguments: argparse.Namespace, stdout: TextIO, stderr: TextIO) -> ExitCode:
    assignments = _assignments(arguments.assignments)
    operations: list[dict[str, Any]] = []
    for dotted, text in assignments:
        path = split_path(dotted)
        runner = (
            _runner_of(path[1], assignments) if path[:1] == ["actors"] and len(path) > 3 else None
        )
        value = value_of(dotted, text, runner=runner, as_json=arguments.json)
        operations.append({"path": path, "value": value})
    params: dict[str, Any] = {"operations": operations}
    if arguments.reason is not None:
        params["reason"] = arguments.reason
    if arguments.rehearse:
        params["rehearse"] = True
    result = _call(
        "config-set", params, _session(), lambda u: _show_notice(u, stderr), _ignore_cancel
    )
    _notices(result, stderr)
    return _render_change(result, stdout, rehearse=arguments.rehearse)


def _configure_unset(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "paths",
        nargs="+",
        metavar="path",
        help="a value or a group to remove, such as actors.tester",
    )
    parser.add_argument("--reason", help="why, recorded with the change")
    parser.add_argument(
        "--rehearse",
        action="store_true",
        help="change nothing: show what would be recorded and written",
    )


def _run_unset(arguments: argparse.Namespace, stdout: TextIO, stderr: TextIO) -> ExitCode:
    params: dict[str, Any] = {
        "operations": [{"path": split_path(p), "unset": True} for p in arguments.paths]
    }
    if arguments.reason is not None:
        params["reason"] = arguments.reason
    if arguments.rehearse:
        params["rehearse"] = True
    result = _call(
        "config-set", params, _session(), lambda u: _show_notice(u, stderr), _ignore_cancel
    )
    _notices(result, stderr)
    return _render_change(result, stdout, rehearse=arguments.rehearse)


# config get


def _configure_get(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "path", nargs="?", metavar="path", help="a value or group, such as actors.tester"
    )
    parser.add_argument("--json", action="store_true", help="print the result as JSON")


def _conflict_lines(conflict: dict[str, Any]) -> list[str]:
    where = ", ".join(".".join(path) for path in conflict["paths"])
    head = (
        f"conflict at {where}: together these changes break a rule ({conflict['rule']})"
        if "rule" in conflict
        else f"conflict at {where}: these changes set it differently"
    )
    lines = [head]
    for change in conflict["changes"]:
        who = change["actor"].get("id", "someone unknown")
        lines.append(f"  change {change['change']} by {who} at {change['at']}:")
        lines += [f"    {_entry_line(entry)}" for entry in change["entries"]]
    return lines


def _run_get(arguments: argparse.Namespace, stdout: TextIO, stderr: TextIO) -> ExitCode:
    params: dict[str, Any] = {}
    if arguments.path is not None:
        params["path"] = split_path(arguments.path)
    result = _call("config-get", params, _session(), lambda u: None, _ignore_cancel)
    _notices(result, stderr)
    if arguments.json:
        print(json.dumps(result, ensure_ascii=False), file=stdout)
        return ExitCode.OK
    if "value" not in result:
        where = arguments.path or "config"
        print(f"Nothing is set at {where}." if arguments.path else "Config is empty.", file=stdout)
        del where
    elif isinstance(result["value"], str):
        print(result["value"], file=stdout)
    else:
        print(json.dumps(result["value"], ensure_ascii=False, indent=2), file=stdout)
    for conflict in result["conflicts"]:
        print("\n".join(_conflict_lines(conflict)), file=stdout)
    return ExitCode.OK


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
    params: dict[str, Any] = {"force": True} if arguments.force else {}
    if arguments.rehearse:
        params["rehearse"] = True
    result = _call("flush", params, _session(), lambda u: _show_notice(u, stderr), _ignore_cancel)
    _notices(result, stderr)
    if not result["files"]:
        print("Nothing to do: the config files are what config says.", file=stdout)
        return ExitCode.OK
    would = "would " if arguments.rehearse else ""
    for file in result["files"]:
        print(would + _file_line(file, rehearse=arguments.rehearse), file=stdout)
    if arguments.rehearse:
        print("Rehearsal: nothing was written.", file=stdout)
        return ExitCode.WOULD_CHANGE
    return ExitCode.OK


COMMANDS: tuple[Command, ...] = (
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
