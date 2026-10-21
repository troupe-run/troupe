"""perform, status and logs on the command line (spec: cli; perform-status-logs design D14;
config-model design D14).

Each command builds its request as data and calls the core through the client protocol's
dispatcher, in process, then renders the updates and the result. Nothing here decides anything
the core does. ``perform`` names an actor and its direction: the runner, its options, the effect
check and the character are the actor's config.
"""

import argparse
import asyncio
import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any, TextIO

from troupe.cli.parser import Command
from troupe.cli.render import render_error, render_event, render_notice, render_run, render_run_line
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
    parser.add_argument("actor", help="the actor's name, as config defines it")
    parser.add_argument("--direction", help="what the actor is asked to do in this run")
    parser.add_argument(
        "--rehearse",
        action="store_true",
        help="run every check and start nothing: show what would run",
    )


def _text(summary: dict[str, Any] | None) -> str:
    if summary is None:
        return "none"
    return f"{summary['length']} characters, {summary['hash']}"


def _render_rehearsal(rehearsal: dict[str, Any], stdout: TextIO) -> None:
    check = rehearsal["effectCheck"]
    expect = ", ".join(check["paths"]) if check["kind"] == "files" else "no effect check"
    stage = rehearsal["stage"]
    lines = [
        f"would perform {rehearsal['actor']}",
        f"  runner: {rehearsal['runner']}",
        f"  stage: {stage['name']}, effects {stage['effects']}",
        f"  effect check: {expect}",
        f"  character: {_text(rehearsal.get('character'))}",
        f"  direction: {_text(rehearsal.get('direction'))}",
        f"  config: {', '.join(rehearsal['config'])}",
        "Rehearsal: nothing was started or recorded.",
    ]
    print("\n".join(lines), file=stdout)


def _run_perform(arguments: argparse.Namespace, stdout: TextIO, stderr: TextIO) -> ExitCode:
    session = _session()
    params: dict[str, Any] = {"actor": arguments.actor}
    if arguments.direction is not None:
        params["direction"] = arguments.direction
    if arguments.rehearse:
        params["rehearse"] = True

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
    if "rehearsal" in result:
        _render_rehearsal(result["rehearsal"], stdout)
        return ExitCode.WOULD_CHANGE
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
