"""The Bug a failed release install check opens names the tag, each failed leg and the run, and no
issue is opened when every leg passed (spec: installation; install-from-tag design D6).

Its tests that stay in their own process are in unit/test_release_check_report.py."""

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from conftest import SCRIPTS
from release_check_report_shared import JOBS, RELEASE, RUN, TAG, failing

import release_check_report
from release_check_report import Failed


def run_script(tmp_path: Path, jobs: dict[str, Any]) -> subprocess.CompletedProcess[str]:
    path = tmp_path / "jobs.json"
    path.write_text(json.dumps(jobs), encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(SCRIPTS / "release_check_report.py"), str(path), TAG, RUN, RELEASE],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )


def test_the_script_prints_the_issue_as_json_when_a_leg_failed(tmp_path: Path) -> None:
    done = run_script(tmp_path, failing(("ubuntu-latest", "3.12", "failure")))
    assert done.returncode == 0, done.stderr
    printed = json.loads(done.stdout)
    assert printed == release_check_report.issue(
        [Failed("Linux", "3.12", "failure", f"{RUN}/job/124479681699")], TAG, RUN, RELEASE
    )


def test_the_script_prints_nothing_when_every_leg_passed(tmp_path: Path) -> None:
    done = run_script(tmp_path, JOBS)
    assert (done.returncode, done.stdout) == (0, "")
