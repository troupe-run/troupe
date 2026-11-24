"""A push is judged on its own only when its previous head's latest `check` passed; anything else
diffs the whole pull request, and a malformed input is refused (spec: quality-check; ci-check-scope
D1, ci-once-per-commit D3).

Its tests that stay in their own process are in unit/test_check_range.py."""

import json
import subprocess
import sys
from pathlib import Path

import pytest
from check_range_shared import BASE, BEFORE, EARLY, HEAD, LATE, WHOLE, check_run
from conftest import REPO


def runs_file(tmp_path: Path, *runs: dict[str, str | None]) -> str:
    path = tmp_path / "check-runs.json"
    path.write_text(json.dumps({"total_count": len(runs), "check_runs": list(runs)}), "utf-8")
    return str(path)


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(REPO / "scripts" / "check_range.py"), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_the_script_narrows_on_a_passing_latest_check_and_exits_0(tmp_path: Path) -> None:
    passed = runs_file(tmp_path, check_run("skipped", EARLY), check_run("success", LATE))
    result = run("synchronize", BEFORE, BASE, HEAD, passed)
    assert (result.returncode, result.stdout, result.stderr) == (0, f"{BEFORE} {HEAD}\n", "")


def test_the_script_diffs_the_whole_pull_request_with_no_check_runs() -> None:
    result = run("synchronize", BEFORE, BASE, HEAD, "")
    assert (result.returncode, result.stdout, result.stderr) == (0, f"{WHOLE}\n", "")


def test_a_refusal_exits_1_and_prints_nothing_on_stdout(tmp_path: Path) -> None:
    result = run("synchronize", "", BASE, HEAD, runs_file(tmp_path, check_run("success", LATE)))
    assert (result.returncode, result.stdout) == (1, "")
    assert result.stderr.startswith("check_range: BEFORE ``")


@pytest.mark.parametrize("args", [(), ("synchronize", BEFORE, BASE, HEAD)])
def test_a_wrong_number_of_arguments_fails_naming_what_to_pass(args: tuple[str, ...]) -> None:
    result = run(*args)
    assert (result.returncode, result.stdout) == (1, "")
    assert f"expected 5 arguments (ACTION BEFORE BASE HEAD CHECK_RUNS), got {len(args)}" in (
        result.stderr
    )


@pytest.mark.parametrize("content", ["not json", '{"check_runs": "none"}'])
def test_unreadable_check_runs_exit_1_naming_the_file(tmp_path: Path, content: str) -> None:
    path = tmp_path / "check-runs.json"
    path.write_text(content, encoding="utf-8")
    result = run("synchronize", BEFORE, BASE, HEAD, str(path))
    assert (result.returncode, result.stdout) == (1, "")
    assert f"CHECK_RUNS `{path}`" in result.stderr


def test_a_missing_check_runs_file_exits_1_naming_it(tmp_path: Path) -> None:
    missing = tmp_path / "absent.json"
    result = run("synchronize", BEFORE, BASE, HEAD, str(missing))
    assert (result.returncode, result.stdout) == (1, "")
    assert f"CHECK_RUNS `{missing}` can't be read" in result.stderr
