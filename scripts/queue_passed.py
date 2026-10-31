"""Answer, for a push to main, whether the merge queue already passed this exact commit.

Usage (in .github/workflows/ci.yml's `changes` job, on a push to main):
    python3 scripts/queue_passed.py --repository "$GITHUB_REPOSITORY" --sha "$GITHUB_SHA" \
        >> "$GITHUB_OUTPUT"

Prints the `changes` job's answers (spec: quality-check, "A push to main skips a commit the merge
queue passed"; ci-once-per-commit design D1):
- `scope=none` and `check-args=` when CI's merge-queue run on this commit succeeded: the queue ran
  the full check on every leg, so the legs skip and `check` passes;
- `scope=full` and `check-args=` otherwise, so every leg runs the full check.

Only a `merge_group` run of ci.yml counts: a pull request's run may have been scoped or skipped.
Any one that succeeded is enough, since a re-run tested the same tree. One still waiting is polled,
up to LIMIT_SECONDS, because the queue can land a commit just before its run closes.

It always exits 0. A read that fails, output it can't read, or a status it doesn't know answers
"full", with a warning saying why, and the tests decide the run.

Adapted from troupe-run/infrastructure's scripts/queue_passed.py (its ci-once-per-commit design
D1-D4), which also answers whether the guard's tests run. A fix to one likely belongs in both.

Standard library and gh only: the job runs it with the runner's python3, before anything is set up.
"""

import argparse
import json
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

LIMIT_SECONDS = 2 * 60
POLL_SECONDS = 10
WAITING = frozenset({"queued", "in_progress", "waiting", "requested", "pending"})
SKIP = "scope=none\ncheck-args="
FULL = "scope=full\ncheck-args="

Gh = Callable[[list[str]], Any]


@dataclass(frozen=True)
class Answer:
    """Whether the queue passed the commit, why, in a sentence for the run's log, and whether
    that's a warning: an answer of "full" because something couldn't be read or understood."""

    passed: bool
    why: str
    warning: bool = False


class ReadError(Exception):
    """A read of GitHub that failed, or answered in a shape this doesn't expect."""


def gh(args: list[str]) -> Any:  # noqa: ANN401 (JSON)
    result = subprocess.run(["gh", *args], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise ReadError(result.stderr.strip() or f"gh exited {result.returncode}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise ReadError(f"gh run list printed something that isn't JSON: {error}") from error


def queue_runs(gh_: Gh, repository: str, sha: str) -> list[dict[str, str]]:
    """CI's merge-queue runs on this commit: each one's status and conclusion."""
    found = gh_(
        [
            "run", "list", "--repo", repository, "--workflow", "ci.yml", "--commit", sha,
            "--event", "merge_group", "--json", "status,conclusion", "--limit", "20",
        ]
    )  # fmt: skip
    if not (
        isinstance(found, list)
        and all(
            isinstance(run, dict)
            and isinstance(run.get("status"), str)
            and isinstance(run.get("conclusion"), str)
            for run in found
        )
    ):
        raise ReadError("gh run list's answer isn't a list of runs with a status and conclusion")
    return found


def decide(
    gh_: Gh,
    repository: str,
    sha: str,
    *,
    now: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> Answer:
    start = now()
    while True:
        try:
            runs = queue_runs(gh_, repository, sha)
        except ReadError as error:
            return Answer(False, f"CI's merge-queue runs on {sha} couldn't be read: {error}", True)
        if any(run["status"] == "completed" and run["conclusion"] == "success" for run in runs):
            return Answer(True, f"the merge queue passed {sha}")
        unknown = [run["status"] for run in runs if run["status"] not in WAITING | {"completed"}]
        if unknown:
            why = f"a merge-queue run on {sha} has a status this doesn't know: {unknown[0]}"
            return Answer(False, why, True)
        if not any(run["status"] in WAITING for run in runs):
            if not runs:
                return Answer(False, f"no merge-queue run of CI tested {sha}")
            concluded = ", ".join(sorted({run["conclusion"] for run in runs}))
            return Answer(False, f"CI's merge-queue runs on {sha} concluded {concluded}")
        if now() - start >= LIMIT_SECONDS:
            why = f"CI's merge-queue run on {sha} didn't finish within {LIMIT_SECONDS}s"
            return Answer(False, why, True)
        sleep(POLL_SECONDS)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repository", required=True, help="owner/name, for gh")
    parser.add_argument("--sha", required=True, help="the commit pushed to main")
    args = parser.parse_args(argv)
    answer = decide(gh, args.repository, args.sha)
    # Only name=value lines on stdout: the workflow appends it to $GITHUB_OUTPUT.
    print(SKIP if answer.passed else FULL)
    if answer.passed:
        print(f"{answer.why}, so its legs aren't run again.", file=sys.stderr)
    elif answer.warning:
        print(f"::warning::queue_passed.py: {answer.why}; running every leg.", file=sys.stderr)
    else:
        print(f"{answer.why}, so every leg runs the full check.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
