"""What a flow's step is told, and what it can read of the steps before it (spec: flows, "A step
is told the performance's direction, its own, and the step before", "Earlier steps' history is
readable in each step's worktree"; actor-sequences design D6).

A step's direction holds, in order: the performance's direction, the step's own direction, the
previous step's brief in full, and one line for each earlier step. It's stored by reference, as
every direction is, so the run's start records exactly what the step was told. Before its runner
starts, the step's worktree also holds ``.troupe/performance/<n>-<actor>/`` for each earlier
step: its brief, its diff and its log. ``.troupe/`` is never part of a diff, and no runner's
tools change anything under it.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from troupe.core.client import messages as m

HISTORY = ".troupe/performance"
"""Where a step's worktree holds the history of the steps before it, relative to the theatre's
place in the worktree."""

_DIFF_PATH = re.compile(rb"^diff --git a/(.+?) b/(.+)$", re.MULTILINE)


@dataclass(frozen=True)
class Earlier:
    """A step that has run: where it was, its actor, how it ended, what it changed, what it
    said last, and its log, as its run's events recorded them."""

    index: int
    actor: str
    outcome: str
    files: tuple[str, ...]
    message: str | None
    diff: bytes | None
    log: Sequence[m.LogEntry]

    @property
    def folder(self) -> str:
        """Its history folder, relative to the theatre's place in a later step's worktree."""
        return f"{HISTORY}/{self.index}-{self.actor}"

    def brief(self) -> str:
        """Its brief, in full."""
        files = ", ".join(self.files) if self.files else "nothing"
        lines = [
            f"Step {self.index}, {self.actor}: {self.outcome}.",
            f"Files it changed: {files}.",
        ]
        if self.message:
            lines.append(f"What it said last: {self.message}")
        return "\n".join(lines)

    def line(self) -> str:
        """Its one line in a later step's direction."""
        count = len(self.files)
        noun = "file" if count == 1 else "files"
        return f"{self.index} {self.actor}, {self.outcome}, {count} {noun}: {self.folder}/"


def changed_files(diff: bytes | None) -> tuple[str, ...]:
    """The files a git diff changes, from its ``diff --git`` headers, in its order."""
    if not diff:
        return ()
    found: list[str] = []
    for old, new in _DIFF_PATH.findall(diff):
        name = (new if new != b"/dev/null" else old).decode("utf-8", "replace")
        if name not in found:
            found.append(name)
    return tuple(found)


def final_message(ended: dict[str, Any] | None) -> str | None:
    """The message of a run's result, as its end recorded it; None when it has none."""
    result = ((ended or {}).get("outcome") or {}).get("result") or {}
    message = result.get("message") if isinstance(result, dict) else None
    return message if isinstance(message, str) and message else None


def direction_for(performance: str, own: str | None, earlier: Sequence[Earlier]) -> str:
    """What a step is told: the performance's direction, its own, the previous step's brief in
    full, and a line for each earlier step. A first step is told the performance's direction
    alone, as a single run is."""
    if not earlier and own is None:
        return performance
    parts = [performance] if performance else []
    if own:
        parts.append(own)
    if earlier:
        parts.append("The step before this one:\n" + earlier[-1].brief())
        lines = "\n".join(step.line() for step in earlier)
        parts.append(
            "Earlier steps, each with its brief, diff and log in the folder named:\n" + lines
        )
    return "\n\n".join(parts)


def log_text(log: Sequence[m.LogEntry]) -> str:
    """A run's log as plain text, one line per event or notice, as it was recorded (credentials
    already masked when it was)."""
    lines: list[str] = []
    for entry in log:
        data = entry.to_data()
        if data.get("kind") == "event":
            event = data["event"]
            detail = {k: v for k, v in event.items() if k not in ("runId", "seq", "type")}
            lines.append(f"{data['at']} {event.get('type')}: {detail}")
        else:
            notice = data.get("notice", {})
            lines.append(f"{data.get('at')} notice {notice.get('code')}: {notice.get('problem')}")
    return "\n".join(lines) + ("\n" if lines else "")


def history_files(earlier: Sequence[Earlier]) -> dict[str, bytes]:
    """The history files a step's worktree holds, by path relative to the theatre's place in
    it: each earlier step's brief, diff (when it had one) and log."""
    files: dict[str, bytes] = {}
    for step in earlier:
        files[f"{step.folder}/brief.md"] = (step.brief() + "\n").encode("utf-8")
        if step.diff:
            files[f"{step.folder}/changes.diff"] = step.diff
        files[f"{step.folder}/log.md"] = log_text(step.log).encode("utf-8")
    return files
