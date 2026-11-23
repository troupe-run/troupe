"""config set, config unset, config mv, config get, config drop, config keep and sync on the
command line (spec: cli, config, config-hand-edits, config-renames; config-model design D10;
abandoned-edits design D8; config-mv design D5).

Each builds its request as data and calls the core through the client protocol's dispatcher, then
renders the result: what changed on standard output, notices on standard error. Typing a value by
its schema is the CLI's job (troupe.cli.values), since the core's requests carry JSON.
"""

import argparse
import json
from typing import Any, TextIO

from troupe.cli.commands import _call, _ignore_cancel, _notices, _session
from troupe.cli.render import render_notice
from troupe.cli.runtimes import runtime_lines
from troupe.core.config_paths import parse, parse_prefix, shown
from troupe.core.errors import TroupeError
from troupe.core.exit_codes import ExitCode


def _show_notice(update: dict[str, Any], stderr: TextIO) -> None:
    if update.get("kind") == "notice":
        print(render_notice(update["notice"]), file=stderr, flush=True)


SHOWN = 72
"""The most of a value a conflict shows, in characters of its JSON."""


def _entry_line(entry: dict[str, Any], *, value: bool = False) -> str:
    """What one entry did. With ``value``, what it set the value to, shortened past ``SHOWN``."""
    path = shown(entry["path"])
    if "renamedFrom" in entry:
        return f"renamed {shown(entry['renamedFrom'])} to {path}"
    if "after" not in entry:
        return f"unset {path}"
    line = f"{'changed' if 'before' in entry else 'set'} {path}"
    if not value:
        return line
    after = json.dumps(entry["after"], ensure_ascii=False)
    if len(after) > SHOWN:
        after = f"{after[:SHOWN]}... ({len(after)} characters in all)"
    return f"{line} to {after}"


def _file_line(file: dict[str, Any], *, rehearse: bool = False) -> str:
    verb = {"write": "wrote", "remove": "removed", "finish": "finished", "discard": "discarded"}
    if rehearse:
        verb = {action: action for action in verb}
    line = f"{verb[file['action']]} {file['path']} ({file['reason']})"
    if "kept" in file:
        line += f"; what it held is kept as {file['kept']}"
    if file.get("resolve") is True:
        line += "; and mark it resolved in git" if rehearse else "; marked it resolved in git"
    return line


# config set and config unset


Assignment = tuple[tuple[str, ...], str]
"""A path's keys and the text of the value set there."""


def _runner_of(actor: str, assignments: list[Assignment]) -> str | None:
    """The runner the actor will have: set in this command, or already in config."""
    for path, text in assignments:
        if path == ("actors", actor, "runner") and not text.startswith("@"):
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


def _assignments(raw: list[str]) -> list[Assignment]:
    """Each ``<path>=<value>``: the path ends at the first ``=`` outside brackets (design D4).

    One with no ``=`` is named by its position, never quoted: a value typed after a space instead
    of an ``=`` is read as part of a path, so the argument can be a password (spec: config, "A
    refused config value is repeated nowhere"; config-set-json-redacts, review of #384)."""
    found: list[Assignment] = []
    for position, each in enumerate(raw, start=1):
        path, end = parse_prefix(each)
        if end == len(each):
            raise TroupeError(
                "config.invalid",
                problem=f"path=value {position} doesn't set anything: a value is written "
                "<path>=<value>.",
                fix="Write it as <path>=<value>, with no space around the =, or use troupe "
                "config unset <path> to remove a value.",
                details={"path": [], "rule": "a value is written <path>=<value>"},
            )
        found.append((path, each[end + 1 :]))
    return found


def _hand_edit_lines(result: dict[str, Any], *, rehearse: bool) -> list[str]:
    """The sweep's hand edits the command recorded (or, rehearsed, would), one line each: they're
    changes too, though not the command's own (spec: config-hand-edits)."""
    would = "would " if rehearse else ""
    lines = []
    for notice in result["notices"]:
        if notice["code"] != "config.hand-edit-recorded":
            continue
        count = notice["details"]["entries"]
        lines.append(
            f"{would}record {notice['details']['file']}: an edit by an unknown author "
            f"({count} value{'s' if count != 1 else ''})"
        )
    return lines


def _render_change(result: dict[str, Any], stdout: TextIO, *, rehearse: bool) -> ExitCode:
    edits = _hand_edit_lines(result, rehearse=rehearse)
    for line in edits:
        print(line, file=stdout)
    if not result["entries"]:
        if edits:
            print(
                "The command's own change changes nothing: config already holds that.", file=stdout
            )
        else:
            print("Nothing changed: config already holds that.", file=stdout)
        if rehearse and edits:
            print("Rehearsal: nothing was recorded or written.", file=stdout)
            return ExitCode.WOULD_CHANGE
        return ExitCode.OK
    would = "would " if rehearse else ""
    for entry in result["entries"]:
        line = _entry_line(entry)
        if rehearse and "renamedFrom" in entry:
            line = "rename" + line.removeprefix("renamed")
        print(would + line, file=stdout)
    for file in result["files"]:
        print(would + _file_line(file, rehearse=rehearse), file=stdout)
    if "change" in result:
        print(f"recorded change {result['change']}", file=stdout)
    if rehearse:
        print("Rehearsal: nothing was recorded or written.", file=stdout)
        return ExitCode.WOULD_CHANGE
    return ExitCode.OK


def run_set(arguments: argparse.Namespace, stdout: TextIO, stderr: TextIO) -> ExitCode:
    # Only set types values by their schema: get and sync don't load YAML or schema checking
    # (cli-starts-fast design D5).
    from troupe.cli.values import value_of

    assignments = _assignments(arguments.assignments)
    operations: list[dict[str, Any]] = []
    for path, text in assignments:
        runner = (
            _runner_of(path[1], assignments) if path[:1] == ("actors",) and len(path) > 3 else None
        )
        value = value_of(path, text, runner=runner, as_json=arguments.json)
        operations.append({"path": list(path), "value": value})
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


def run_unset(arguments: argparse.Namespace, stdout: TextIO, stderr: TextIO) -> ExitCode:
    params: dict[str, Any] = {
        "operations": [{"path": list(parse(p)), "unset": True} for p in arguments.paths]
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


def run_mv(arguments: argparse.Namespace, stdout: TextIO, stderr: TextIO) -> ExitCode:
    """config mv: one rename operation (config-mv design D5); the core checks it."""
    operation = {"path": list(parse(arguments.new)), "renamedFrom": list(parse(arguments.old))}
    params: dict[str, Any] = {"operations": [operation]}
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


def _conflict_lines(conflict: dict[str, Any]) -> list[str]:
    where = ", ".join(shown(path) for path in conflict["paths"])
    head = (
        f"conflict at {where}: together these changes break a rule ({conflict['rule']})"
        if "rule" in conflict
        else f"conflict at {where}: these changes set it differently"
    )
    lines = [head]
    for change in conflict["changes"]:
        who = change["actor"].get("id", "someone unknown")
        lines.append(f"  change {change['change']} by {who} at {change['at']}:")
        lines += [f"    {_entry_line(entry, value=True)}" for entry in change["entries"]]
    return lines


def run_get(arguments: argparse.Namespace, stdout: TextIO, stderr: TextIO) -> ExitCode:
    params: dict[str, Any] = {}
    path = None if arguments.path is None else parse(arguments.path)
    if path is not None:
        params["path"] = list(path)
    if arguments.resolved:
        params["resolved"] = True
    result = _call("config-get", params, _session(), lambda u: None, _ignore_cancel)
    _notices(result, stderr)
    if arguments.json:
        print(json.dumps(result, ensure_ascii=False), file=stdout)
        return ExitCode.OK
    if arguments.resolved:
        for runtime in result["runtimes"].values():
            print("\n".join(runtime_lines(runtime)), file=stdout)
        for conflict in result["conflicts"]:
            print("\n".join(_conflict_lines(conflict)), file=stdout)
        return ExitCode.OK
    if "value" not in result:
        print(f"Nothing is set at {shown(path)}." if path else "Config is empty.", file=stdout)
    elif isinstance(result["value"], str):
        print(result["value"], file=stdout)
    else:
        print(json.dumps(result["value"], ensure_ascii=False, indent=2), file=stdout)
    for conflict in result["conflicts"]:
        print("\n".join(_conflict_lines(conflict)), file=stdout)
    return ExitCode.OK


# sync


def run_sync(arguments: argparse.Namespace, stdout: TextIO, stderr: TextIO) -> ExitCode:
    params: dict[str, Any] = {"force": True} if arguments.force else {}
    if arguments.rehearse:
        params["rehearse"] = True
    result = _call("sync", params, _session(), lambda u: _show_notice(u, stderr), _ignore_cancel)
    _notices(result, stderr)
    would = "would " if arguments.rehearse else ""
    for edit in result["edits"]:
        count = len(edit["entries"])
        print(
            f"{would}record {edit['path']}: an edit by an unknown author "
            f"({count} value{'s' if count != 1 else ''})",
            file=stdout,
        )
    if not result["files"] and not result["edits"]:
        print("Nothing to do: the config files are what config says.", file=stdout)
        return ExitCode.OK
    for file in result["files"]:
        print(would + _file_line(file, rehearse=arguments.rehearse), file=stdout)
    if arguments.rehearse:
        print("Rehearsal: nothing was recorded or written.", file=stdout)
        return ExitCode.WOULD_CHANGE
    return ExitCode.OK


# config drop and config keep (abandoned-edits design D8)


def run_drop(arguments: argparse.Namespace, stdout: TextIO, stderr: TextIO) -> ExitCode:
    params: dict[str, Any] = {"change": arguments.change}
    if arguments.rehearse:
        params["rehearse"] = True
    result = _call(
        "config-drop", params, _session(), lambda u: _show_notice(u, stderr), _ignore_cancel
    )
    _notices(result, stderr)
    count = len(result["changes"])
    verb = "Would drop" if result["rehearsed"] else "Dropped"
    removed = "would remove" if result["rehearsed"] else "removed"
    print(
        f"{verb} {count} change{'s' if count != 1 else ''} ({', '.join(result['changes'])}): "
        f"{removed} "
        f"{', '.join(result['segments'])}.",
        file=stdout,
    )
    if result["rehearsed"]:
        print("Rehearsal: nothing was removed.", file=stdout)
        return ExitCode.WOULD_CHANGE
    return ExitCode.OK


def run_keep(arguments: argparse.Namespace, stdout: TextIO, stderr: TextIO) -> ExitCode:
    params: dict[str, Any] = {"change": arguments.change}
    if arguments.rehearse:
        params["rehearse"] = True
    result = _call(
        "config-keep", params, _session(), lambda u: _show_notice(u, stderr), _ignore_cancel
    )
    _notices(result, stderr)
    if result["rehearsed"]:
        print(f"Would keep the changes of {result['change']}.", file=stdout)
        print("Rehearsal: nothing was written.", file=stdout)
        return ExitCode.WOULD_CHANGE
    print(
        f"Kept the changes of {result['change']}; troupe won't ask about them again.",
        file=stdout,
    )
    return ExitCode.OK
