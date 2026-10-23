"""Turn structured results and errors into text for a terminal."""

from collections.abc import Mapping
from typing import Any

from troupe.core.errors import TroupeError
from troupe.platform.paths import friendly


def render_error(error: TroupeError) -> str:
    """The text written to standard error for ``error``: problem, then path, then fix."""
    lines = [f"troupe: {error.problem}"]
    if error.path is not None:
        lines.append(f"  path: {friendly(error.path)}")
    lines.append(f"  fix: {error.fix}")
    return "\n".join(lines)


def render_notice(notice: Mapping[str, Any]) -> str:
    """The text written to standard error for a notice (notice.schema.json data)."""
    lines = [f"troupe: {notice['problem']}"]
    if notice.get("path") is not None:
        lines.append(f"  path: {friendly(str(notice['path']))}")
    lines.append(f"  fix: {notice['fix']}")
    return "\n".join(lines)


def _first_line(text: object, limit: int = 100) -> str:
    line = str(text).strip().splitlines()[0] if str(text).strip() else ""
    return line if len(line) <= limit else line[: limit - 1] + "…"


def render_event(logged: Mapping[str, Any]) -> str:
    """One line for a recorded run event (run.schema.json#/$defs/loggedEvent data)."""
    event = logged["event"]
    kind = event["type"]
    summaries: dict[str, str] = {
        "init": f"{event.get('runner', {}).get('name')} {event.get('runner', {}).get('version')}",
        "turn": f"{event.get('role')}: {_first_line(event.get('text', ''))}",
        "tool_call": f"{event.get('tool')} {_first_line(event.get('inputSummary', ''))}",
        "tool_result": f"{'error' if event.get('isError') else 'ok'} "
        f"{_first_line(event.get('outputSummary', ''))}",
        "retry": f"attempt {event.get('attempt')}, {event.get('reason')}",
        "log": f"{event.get('level')}: {_first_line(event.get('message', ''))}",
        "result": f"{event.get('status')}: {_first_line(event.get('message', ''))}",
        "oversized": f"{event.get('originalType')}, {event.get('bytes')} bytes, {event.get('ref')}",
    }
    return f"  {logged['seq']:>4} {logged['at']} {kind}: {summaries.get(kind, '')}".rstrip()


def render_run(run: Mapping[str, Any]) -> list[str]:
    """A run's summary (run.schema.json#/$defs/summary data), one fact per line. A field the
    summary leaves out has nothing to say, so its line is left out too (or shows -)."""
    reported = run["runner"].get("reported")
    started_by = run["startedBy"]
    lines = [
        f"run {run['runId']}",
        f"  actor: {run['actor']}",
        f"  started by: {started_by.get('id', started_by['kind'])} at {run['startedAt']}",
        f"  runner: {run['runner']['requested']}"
        + (f" ({reported['name']} {reported['version']})" if reported else ""),
        f"  stage: {run['stage']['name']}, effects {run['stage']['effects']}",
        f"  workspace: {_workspace(run['workspace'])}",
        f"  state: {run['state']}",
        f"  outcome: {run.get('outcome', '-')}",
        f"  events: {run['events']}",
    ]
    if "error" in run:
        lines.append(f"  error: {run['error']['code']}: {run['error']['problem']}")
    if "endedAt" in run:
        lines.append(f"  ended: {run['endedAt']}")
    if "transcript" in run:
        lines.append(f"  transcript: {run['transcript']}")
    if "stderr" in run:
        lines.append(f"  stderr: {run['stderr']}")
    if "recording" in run:
        failed = run["recording"]
        lines.append(
            f"  recording stopped at event {failed['failedAt']}: {failed['error']['code']}"
        )
    if "changes" in run:
        lines.extend(_changes(run["changes"]))
    return lines


def _workspace(workspace: Mapping[str, Any]) -> str:
    if workspace["kind"] == "theatre":
        return "the theatre"
    dirty = ", the theatre had uncommitted changes it didn't see" if workspace["dirty"] else ""
    return f"its own worktree at {workspace['base'][:12]}{dirty}"


def _changes(changes: Mapping[str, Any]) -> list[str]:
    """A worktree run's changes, for its summary."""
    state = changes["state"]
    line = f"  changes: {state}"
    if "added" in changes:
        line += (
            f" ({changes['added']} added, {changes['modified']} modified, "
            f"{changes['deleted']} deleted"
            + (f", {changes['leftOut']} under .troupe/ left out" if changes["leftOut"] else "")
            + ")"
        )
    if "settledAt" in changes:
        line += f" at {changes['settledAt']}"
    lines = [line]
    if "diff" in changes:
        lines.append(f"  diff: {changes['diff']}")
    if "worktree" in changes:
        lines.append(f"  worktree: {changes['worktree']}")
    if "error" in changes:
        lines.append(f"  capture failed: {changes['error']['code']}: {changes['error']['problem']}")
    for kind, entries in changes.get("shared", {}).items():
        named = ", ".join(f"{entry['name']} {entry['change']}" for entry in entries)
        lines.append(f"  changed in git while it ran ({kind}): {named}")
    return lines


def render_run_line(run: Mapping[str, Any]) -> str:
    """One line for a run in a list."""
    status = run["outcome"] if run["state"] == "ended" else run["state"]
    return (
        f"{run['runId']}  {status:<20} {run['actor']:<16} {run['startedAt']}  "
        f"{run['events']} events"
    )
