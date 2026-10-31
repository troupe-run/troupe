"""Decide which revisions CI's `changes` job diffs (spec: quality-check; ci-check-scope D1).

Usage: python3 scripts/check_range.py ACTION BEFORE BASE HEAD CHECK_RUNS

ACTION is the pull_request event's action, BEFORE the previous head's sha (empty when the event
has none), BASE and HEAD the pull request's shas, and CHECK_RUNS the path of the check-runs API's
JSON for the previous head's `check` (empty when none was looked up). Prints the revisions for
`git diff --name-only`, which split on the space:

- `<before> <head>` when a push adds to a pull request whose previous head passed `check`: the two
  trees, compared directly, so only what this push changed decides
- `<base>...<head>` otherwise: every path the pull request changes

Only the latest `check` on the previous head counts, by when it started (ci-once-per-commit design
D3). A head checked as a draft and again once ready carries two, one per workflow run, and the
draft's is skipped: it must never be what lets a push be narrowed.

A malformed input is refused, naming it, and exits 1, so the legs run the full check.

Standard library only: it runs with the runner's python3, before anything is installed.
"""

import json
import re
import sys
from datetime import datetime
from pathlib import Path

SHA = re.compile(r"[0-9a-f]{40}\Z")
ACTIONS = ("opened", "reopened", "synchronize", "ready_for_review")
"""The pull_request actions CI runs on: the event's default types, and a draft marked ready."""


class RangeError(ValueError):
    pass


def _sha(name: str, value: str) -> str:
    if not SHA.match(value):
        raise RangeError(f"{name} `{value}` isn't a sha: it must be 40 lowercase hex characters.")
    return value


def _started(run: object, index: int) -> datetime | None:
    if not isinstance(run, dict):
        raise RangeError(f"check run {index} isn't an object.")
    started = run.get("started_at")
    conclusion = run.get("conclusion")
    if not (conclusion is None or isinstance(conclusion, str)):
        raise RangeError(f"check run {index}'s conclusion `{conclusion}` isn't a string or null.")
    if started is None:
        return None
    try:
        if not isinstance(started, str):
            raise ValueError
        return datetime.fromisoformat(started)
    except ValueError:
        raise RangeError(
            f"check run {index}'s started_at `{started}` isn't an ISO 8601 time or null."
        ) from None


def latest_conclusion(document: object) -> str:
    """The conclusion of the `check` run that started last, or "" when there's none.

    A run with no start time counts as the latest. When several runs tie for latest, any that
    didn't succeed decides, so a tie never reads as passed."""
    if not isinstance(document, dict) or not isinstance(document.get("check_runs"), list):
        raise RangeError("the check runs aren't an object with a `check_runs` list.")
    runs: list[dict[str, object]] = document["check_runs"]
    if not runs:
        return ""
    starts = [_started(run, index) for index, run in enumerate(runs)]
    keys = [(start is None, start.timestamp() if start else 0.0) for start in starts]
    latest = max(keys)
    tied = [run for run, key in zip(runs, keys, strict=True) if key == latest]
    conclusions = [str(run.get("conclusion") or "") for run in tied]
    return next((c for c in conclusions if c != "success"), "success")


def read_conclusion(path: str) -> str:
    """The previous head's latest `check` conclusion, from CHECK_RUNS ("" when it's empty)."""
    if not path:
        return ""
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise RangeError(f"CHECK_RUNS `{path}` can't be read as JSON: {error}") from None
    try:
        return latest_conclusion(document)
    except RangeError as error:
        raise RangeError(f"CHECK_RUNS `{path}`: {error}") from None


def revisions(action: str, before: str, base: str, head: str, conclusion: str) -> str:
    """What to diff: the push alone when its previous head passed `check`, else the whole PR."""
    if action not in ACTIONS:
        raise RangeError(f"action `{action}` isn't one CI runs on: {', '.join(ACTIONS)}.")
    base, head = _sha("BASE", base), _sha("HEAD", head)
    if action == "synchronize":
        before = _sha("BEFORE", before)
        if conclusion == "success":
            return f"{before} {head}"
    elif before:
        _sha("BEFORE", before)
    return f"{base}...{head}"


def main(argv: list[str]) -> int:
    if len(argv) != 5:
        print(
            f"check_range: expected 5 arguments (ACTION BEFORE BASE HEAD CHECK_RUNS), got "
            f"{len(argv)}. Fix: pass the event's action, the previous head, the base, the head "
            "and the path of the previous head's check runs, each possibly empty but present.",
            file=sys.stderr,
        )
        return 1
    action, before, base, head, check_runs = argv
    try:
        print(revisions(action, before, base, head, read_conclusion(check_runs)))
    except RangeError as error:
        print(f"check_range: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
