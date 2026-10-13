"""perform, status and logs on the command line (spec: cli; perform-status-logs design D4, D14).

Each command builds its request as data and calls the core through the client protocol's
dispatcher, in process, then renders the updates and the result. Nothing here decides anything
the core does: the CLI finds the theatre, reads the files a person names, and turns paths typed
from the working directory into theatre-relative ones.

``perform``'s flags for the runner, its options and the effect check are interim: config replaces
them (design D4).
"""

import argparse
import asyncio
import json
import os
from collections.abc import Callable
from pathlib import Path, PurePath
from typing import Any, TextIO

from troupe.cli.parser import Command
from troupe.cli.render import render_error, render_event, render_notice, render_run, render_run_line
from troupe.core import strict_json
from troupe.core.client.dispatch import call
from troupe.core.client.session import CancelSignal, Session
from troupe.core.errors import TroupeError
from troupe.core.exit_codes import ExitCode
from troupe.core.notices import Notice
from troupe.core.theatre import find_theatre
from troupe.platform.interrupts import on_interrupt

Update = Callable[[dict[str, Any]], None]


def _session() -> Session:
    return Session(theatre=find_theatre(Path.cwd()), env=dict(os.environ), cancel=CancelSignal())


def _call(
    method: str,
    params: dict[str, Any],
    session: Session,
    on_update: Update,
    on_cancel: Callable[[int], None],
) -> dict[str, Any]:
    """Call the core, with Ctrl-C asking it to cancel rather than stopping troupe."""
    presses = 0

    async def run() -> dict[str, Any]:
        loop = asyncio.get_running_loop()

        def pressed() -> None:
            nonlocal presses
            presses += 1
            session.cancel.request()
            on_cancel(presses)

        def interrupted() -> None:
            # In the signal handler: hand over to the loop rather than print from here.
            session.cancel.request()
            loop.call_soon_threadsafe(pressed)

        with on_interrupt(interrupted):
            return await call(method, params, session, on_update)

    return asyncio.run(run())


# perform


def _configure_perform(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("actor", help="the actor's name")
    parser.add_argument(
        "--runner", required=True, help="the runner to run it with (interim: config replaces it)"
    )
    parser.add_argument(
        "--runner-options",
        metavar="FILE",
        help="a JSON file holding the runner's options, such as the scripted runner's script",
    )
    parser.add_argument("--instructions", help="what the actor is asked to do")
    check = parser.add_mutually_exclusive_group(required=True)
    check.add_argument(
        "--expect",
        action="append",
        metavar="PATH",
        help="a file the run must create or change (repeatable)",
    )
    check.add_argument(
        "--no-effect-check",
        action="store_true",
        help="check nothing after the run; it must be said explicitly",
    )


def _read_options(path: str) -> dict[str, object]:
    where = str(Path(path).absolute())
    try:
        data = strict_json.loads(Path(path).read_bytes())
    except OSError as error:
        problem = f"The runner options file couldn't be read: {error.strerror or error}."
    except strict_json.StrictJSONError as error:
        problem = f"The runner options file isn't strict JSON: {error}."
    else:
        if isinstance(data, dict):
            return data
        problem = f"The runner options file holds a JSON {type(data).__name__}, not an object."
    raise TroupeError(
        "perform.options-invalid",
        problem=problem,
        fix="Give --runner-options a file holding one JSON object, with no repeated keys and no "
        "NaN or Infinity.",
        path=where,
    )


def theatre_path(typed: str, theatre: Path) -> str:
    """``typed``, relative to the working directory, as a theatre-relative path with ``/``."""
    absolute = Path(os.path.normpath(Path.cwd() / typed))
    try:
        relative = absolute.relative_to(theatre)
    except ValueError:
        relative = None
    if relative is None or relative == PurePath():
        raise TroupeError(
            "perform.path-outside-theatre",
            problem=f"--expect {typed} names {absolute}, which isn't a file inside the theatre "
            f"({theatre}).",
            fix="Name a file inside the theatre; the run's workspace is the theatre.",
            path=str(absolute),
            details={"path": typed},
        )
    return relative.as_posix()


def _run_perform(arguments: argparse.Namespace, stdout: TextIO, stderr: TextIO) -> ExitCode:
    session = _session()
    params: dict[str, Any] = {"actor": arguments.actor, "runner": arguments.runner}
    if arguments.runner_options is not None:
        params["options"] = _read_options(arguments.runner_options)
    if arguments.instructions is not None:
        params["instructions"] = arguments.instructions
    if arguments.no_effect_check:
        params["effectCheck"] = {"kind": "none"}
    else:
        paths = [theatre_path(typed, session.theatre) for typed in arguments.expect]
        params["effectCheck"] = {"kind": "files", "paths": list(dict.fromkeys(paths))}

    def on_update(update: dict[str, Any]) -> None:
        if update["kind"] == "started":
            run_id = update["runId"]
            print(
                f"troupe: run {run_id} starting; follow it from another terminal with "
                f"`troupe logs {run_id[:8]} --follow`",
                file=stderr,
                flush=True,
            )
        elif update["kind"] == "event":
            print(render_event(update), file=stderr, flush=True)
        else:
            print(render_notice(update["notice"]), file=stderr, flush=True)

    def on_cancel(presses: int) -> None:
        notice = Notice(
            "run.cancelling",
            problem="Cancelling the run: the runner has been asked to stop, and will be stopped "
            "if it doesn't within its grace period."
            + (" troupe is already cancelling it." if presses > 1 else ""),
            fix="Wait: troupe records how the run ended before it exits, so the run isn't left "
            "unrecorded.",
            details={"presses": presses},
        )
        print(render_notice(notice.to_data()), file=stderr, flush=True)

    result = _call("perform", params, session, on_update, on_cancel)
    run = result["run"]
    if run["outcome"] == "succeeded":
        print(f"run {run['runId']} succeeded", file=stdout)
        return ExitCode.OK
    if run["outcome"] == "cancelled":
        print(f"troupe: run {run['runId']} was cancelled.", file=stderr)
        return ExitCode.CANCELLED
    error = TroupeError(**run["error"])  # every outcome but succeeded and cancelled has one
    print(f"{render_error(error)}\n  run: {run['runId']} ({run['outcome']})", file=stderr)
    return ExitCode.FAILURE


# status and logs


def _configure_status(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("run", nargs="?", help="a run's id, or at least its first 8 characters")
    parser.add_argument("--limit", type=int, help="how many runs to list, newest first")
    parser.add_argument("--json", action="store_true", help="print the result as JSON")


def _notices(result: dict[str, Any], stderr: TextIO) -> None:
    for notice in result["notices"]:
        print(render_notice(notice), file=stderr)


def _ignore_cancel(presses: int) -> None:
    del presses


def _run_status(arguments: argparse.Namespace, stdout: TextIO, stderr: TextIO) -> ExitCode:
    params: dict[str, Any] = {}
    if arguments.run is not None:
        params["run"] = arguments.run
    if arguments.limit is not None:
        params["limit"] = arguments.limit
    result = _call("status", params, _session(), lambda update: None, _ignore_cancel)
    _notices(result, stderr)
    if arguments.json:
        print(json.dumps(result, ensure_ascii=False), file=stdout)
    elif arguments.run is not None:
        print("\n".join(render_run(result["runs"][0])), file=stdout)
    elif result["runs"]:
        print("\n".join(render_run_line(run) for run in result["runs"]), file=stdout)
    else:
        print("No runs yet.", file=stdout)
    return ExitCode.OK


def _configure_logs(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("run", help="a run's id, or at least its first 8 characters")
    parser.add_argument(
        "--follow", action="store_true", help="wait for new events until the run ends"
    )
    parser.add_argument("--json", action="store_true", help="print updates and the result as JSON")


def _run_logs(arguments: argparse.Namespace, stdout: TextIO, stderr: TextIO) -> ExitCode:
    params: dict[str, Any] = {"run": arguments.run}
    if arguments.follow:
        params["follow"] = True
    shown = 0

    def on_update(update: dict[str, Any]) -> None:
        nonlocal shown
        if arguments.json:
            print(json.dumps(update, ensure_ascii=False), file=stdout, flush=True)
        elif update["kind"] == "event":
            print(render_event(update), file=stdout, flush=True)
            shown += 1
        else:
            print(render_notice(update["notice"]), file=stderr, flush=True)

    session = _session()
    result = _call("logs", params, session, on_update, _ignore_cancel)
    _notices(result, stderr)
    if arguments.json:
        print(json.dumps(result, ensure_ascii=False), file=stdout)
    else:
        for event in result["events"][shown:]:
            print(render_event(event), file=stdout)
        run = result["run"]
        print(f"run {run['runId']}: {run.get('outcome', run['state'])}", file=stdout)
    return ExitCode.CANCELLED if session.cancel.requested else ExitCode.OK


COMMANDS: tuple[Command, ...] = (
    Command("perform", "Run one actor and record the run.", _configure_perform, _run_perform),
    Command("status", "Show the most recent runs, or one run.", _configure_status, _run_status),
    Command("logs", "Show a run's events in order.", _configure_logs, _run_logs),
)
