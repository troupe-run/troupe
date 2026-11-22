"""Turn structured results and errors into text for a terminal."""

from collections.abc import Mapping
from decimal import ROUND_HALF_UP, Decimal
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


def _amounts(event: Mapping[str, Any]) -> str:
    """A context event's counts, as ``, tokens 41000 → 9000``, with ``?`` for a side it leaves out
    and nothing for a count it carries neither side of."""
    parts = []
    for name in ("tokens", "messages"):
        before, after = event.get(f"{name}Before"), event.get(f"{name}After")
        if before is not None or after is not None:
            shown = ["?" if value is None else str(value) for value in (before, after)]
            parts.append(f"{name} {shown[0]} → {shown[1]}")
    return "".join(f", {part}" for part in parts)


# A run's tokens and cost (spec: cli, "Status shows a run's tokens and cost" and the requirements
# after it; run-usage-display design D3, D4). One table names each counter, in both forms, so status
# and logs can't name one differently.
COUNTERS = (
    ("inputTokens", "input", "in"),
    ("outputTokens", "output", "out"),
    ("cacheReadTokens", "cache read", "cache read"),
    ("cacheWriteTokens", "cache write", "cache write"),
)
CENT_FRACTION = Decimal("0.0001")
"""A cost is shown to four decimal places."""
COST_KINDS = {
    "reported": "reported by the service",
    "estimated": "estimated from the runtime's price",
}


def _tokens(usage: Mapping[str, Any], *, short: bool) -> str:
    """The counters ``usage`` carries, as ``1,204 input, 9,817 output`` (or ``in``, ``out``); a
    counter it leaves out is left out, never shown as 0."""
    return ", ".join(
        f"{usage[key]:,} {brief if short else name}"
        for key, name, brief in COUNTERS
        if usage.get(key) is not None
    )


def _amount(usd: float, kind: str) -> str:
    """A cost in US dollars to four decimal places, ``~`` before an estimate. A non-zero cost that
    would show as $0.0000 is ``under $0.0001``, and exactly 0 is ``$0``: never a false zero."""
    mark = "~" if kind == "estimated" else ""
    value = Decimal(repr(usd))
    if value == 0:
        return f"{mark}$0"
    shown = value.quantize(CENT_FRACTION, rounding=ROUND_HALF_UP)
    if shown == 0:
        return f"{mark}under ${CENT_FRACTION}"
    return f"{mark}${shown}"


def _result_cost(event: Mapping[str, Any]) -> tuple[float, str] | None:
    """A result event's cost and its kind: ``costUsd`` is reported, ``estimatedCostUsd``
    estimated."""
    if event.get("costUsd") is not None:
        return event["costUsd"], "reported"
    if event.get("estimatedCostUsd") is not None:
        return event["estimatedCostUsd"], "estimated"
    return None


def _result_figures(event: Mapping[str, Any]) -> str:
    """What a result line adds: `` (tokens …; cost …)``, each part only when the result carries it,
    and nothing when it carries neither."""
    parts = []
    tokens = _tokens(event.get("usage") or {}, short=True)
    if tokens:
        parts.append(f"tokens {tokens}")
    cost = _result_cost(event)
    if cost is not None:
        usd, kind = cost
        parts.append(f"cost {_amount(usd, kind)}, {kind}")
    return f" ({'; '.join(parts)})" if parts else ""


def _usage_lines(run: Mapping[str, Any]) -> list[str]:
    """A run summary's ``tokens:`` and ``cost:`` lines, each only when the summary carries it."""
    lines = []
    tokens = _tokens(run.get("usage") or {}, short=False)
    if tokens:
        lines.append(f"  tokens: {tokens}")
    if "cost" in run:
        cost = run["cost"]
        lines.append(f"  cost: {_amount(cost['usd'], cost['kind'])}, {COST_KINDS[cost['kind']]}")
    return lines


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
        "context": f"{event.get('kind')} by {event.get('by')}{_amounts(event)}: "
        f"{_first_line(event.get('message', ''))}",
        "log": f"{event.get('level')}: {_first_line(event.get('message', ''))}",
        "served_model": f"{event.get('model')}",
        "result": f"{event.get('status')}"
        + (f" ({event['reason']}" if "reason" in event else "")
        + (f", not retried: {event['notRetried']}" if "notRetried" in event else "")
        + (")" if "reason" in event else "")
        + f": {_first_line(event.get('message', ''))}"
        + _result_figures(event),
        "oversized": f"{event.get('originalType')}, {event.get('bytes')} bytes, {event.get('ref')}",
    }
    return f"  {logged['seq']:>4} {logged['at']} {kind}: {summaries.get(kind, '')}".rstrip()


def render_logged_notice(logged: Mapping[str, Any]) -> str:
    """One line for a notice a run recorded, among its events (run.schema.json#/$defs/loggedNotice
    data): its seq column is blank, since a notice has none."""
    notice = logged["notice"]
    return f"  {'':>4} {logged['at']} notice {notice['code']}: {_first_line(notice['problem'])}"


def render_log_entry(entry: Mapping[str, Any]) -> str:
    """One line for an entry of a run's log: a run event or a recorded notice."""
    return render_logged_notice(entry) if entry["kind"] == "run-notice" else render_event(entry)


def _notices(run: Mapping[str, Any]) -> list[str]:
    """The notices a run recorded, for its summary: none when it recorded none."""
    if "notices" not in run:
        return []
    lines = ["  notices:"]
    lines.extend(
        f"    {recorded['at']} {recorded['notice']['code']}: "
        f"{_first_line(recorded['notice']['problem'])}"
        for recorded in run["notices"]
    )
    return lines


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
        *_usage_lines(run),
    ]
    if "error" in run:
        lines.append(f"  error: {run['error']['code']}: {run['error']['problem']}")
    lines.extend(render_audit(run))
    if "endedAt" in run:
        lines.append(f"  ended: {run['endedAt']}")
    if "transcript" in run:
        kinds = " (kinds)" if run.get("transcriptFormat") == "kinds" else ""
        lines.append(f"  transcript: {run['transcript']}{kinds}")
    if "stderr" in run:
        lines.append(f"  stderr: {run['stderr']}")
    if "recording" in run:
        failed = run["recording"]
        at = f"event {failed['failedAt']}" if "failedAt" in failed else f"notice {failed['notice']}"
        lines.append(f"  recording stopped at {at}: {failed['error']['code']}")
    if "changes" in run:
        lines.extend(_changes(run["changes"]))
    lines.extend(_notices(run))
    return lines


def render_audit(run: Mapping[str, Any]) -> list[str]:
    """What the audit of a run's changes found, for its summary and its logs (spec: cli, "Status
    and logs show a run's audit"). A run with no audit recorded shows nothing."""
    # Loaded only to show an audit: the effects module is slow to load (cli-starts-fast D4).
    from troupe.core.runners.effects import Change

    audit = run.get("audit")
    if audit is None:
        return []
    if "error" in audit:
        return [f"  audit couldn't run: {audit['error']['code']}: {audit['error']['problem']}"]
    outside = audit["outside"]
    if not outside:
        return ["  audit: every change the run made was declared"]
    count = f"{len(outside)} {'change' if len(outside) == 1 else 'changes'}"
    lines = [f"  audit: {count} outside the declaration"]
    lines.extend(
        "    " + Change(c["path"], c["change"], c["needs"], to=c.get("to")).shown() for c in outside
    )
    if run["workspace"]["kind"] == "theatre":
        lines.append(
            "    A run in the theatre counts every change made there while it ran, by anyone."
        )
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
    count = len(run.get("notices", []))
    noticed = f", {count} {'notice' if count == 1 else 'notices'}" if count else ""
    cost = run.get("cost")
    costed = ""
    if cost is not None:
        estimated = " estimated" if cost["kind"] == "estimated" else ""
        costed = f", {_amount(cost['usd'], cost['kind'])}{estimated}"
    return (
        f"{run['runId']}  {status:<20} {run['actor']:<16} {run['startedAt']}  "
        f"{run['events']} events{noticed}{costed}"
    )
