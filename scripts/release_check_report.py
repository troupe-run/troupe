"""The Bug a failed release install check opens (spec: installation; install-from-tag design D6).

Usage: python3 scripts/release_check_report.py JOBS TAG RUN_URL RELEASE_URL

JOBS is `gh run view <run> --json jobs` for the release install check's run. When any of its
install legs failed, this prints the issue to open as JSON (title, body and type), for
`gh api repos/<owner>/<repo>/issues --input -`. When none did, it prints nothing, and no issue is
opened. A tag is never moved or deleted, so the issue is where a broken release is tracked, and the
fix is the next patch release.

Standard library only, like check_result.py: the workflow's report job runs it with `python3`,
before anything is installed.
"""

import json
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

LEG = re.compile(r"install \((?P<runner>[^,]+), Python (?P<python>[0-9.]+)\)")
"""An install leg's name, as the workflow's matrix job names it."""
PLATFORMS = {"ubuntu-latest": "Linux", "macos-latest": "macOS", "windows-latest": "Windows"}
"""The runner each leg ran on, as people name its platform."""
PASSED = ("success", "skipped")
ISSUE_TYPE = "Bug"


@dataclass(frozen=True)
class Failed:
    """One install leg that didn't pass."""

    platform: str
    python: str
    conclusion: str
    url: str


def failed_legs(jobs: dict[str, Any]) -> list[Failed]:
    """The install legs that didn't pass, in platform then Python order. Other jobs are ignored."""
    found: list[Failed] = []
    for job in jobs["jobs"]:
        leg = LEG.fullmatch(job["name"])
        if leg is None or job["conclusion"] in PASSED:
            continue
        runner = leg.group("runner")
        found.append(
            Failed(
                PLATFORMS.get(runner, runner), leg.group("python"), job["conclusion"], job["url"]
            )
        )
    return sorted(found, key=lambda f: (f.platform, tuple(int(p) for p in f.python.split("."))))


def issue(failed: Sequence[Failed], tag: str, run_url: str, release_url: str) -> dict[str, str]:
    """The Bug to open for a tag whose install check failed on the given legs."""
    rows = "\n".join(
        f"| {leg.platform} | {leg.python} | {leg.conclusion} | [job]({leg.url}) |" for leg in failed
    )
    body = "\n".join(
        [
            f"The release install check failed for `{tag}`: the documented command didn't "
            "install a working troupe on every platform and Python.",
            "",
            "| Platform | Python | Result | Job |",
            "|---|---|---|---|",
            rows,
            "",
            f"- Run: {run_url}",
            f"- Release: {release_url}",
            "",
            "The tag and its release stay as they are: tags are never moved or deleted. Fix it in "
            "a patch release, whose release pull request also moves the documented tag on "
            '(`contributing/releasing.md`, "Checking each release\'s install"). If a leg failed '
            "because of GitHub rather than troupe, re-run the check with "
            f"`gh workflow run release-install-check.yml -f ref={tag}`, and close this with that "
            "run.",
            "",
            "Add this issue to the troupe roadmap board: the workflow's token can't.",
            "",
        ]
    )
    return {"title": f"Install check failed for {tag}", "body": body, "type": ISSUE_TYPE}


def main(argv: Sequence[str]) -> int:
    if len(argv) != 4:
        print(
            "usage: python3 scripts/release_check_report.py JOBS TAG RUN_URL RELEASE_URL",
            file=sys.stderr,
        )
        return 2
    jobs_file, tag, run_url, release_url = argv
    jobs: dict[str, Any] = json.loads(Path(jobs_file).read_text(encoding="utf-8"))
    failed = failed_legs(jobs)
    if failed:
        print(json.dumps(issue(failed, tag, run_url, release_url)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
