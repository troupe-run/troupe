"""The one required `check` passes only when the legs passed, or were skipped because nothing
needed checking (spec: quality-check; ci-check-scope design D3).

Its tests that stay in their own process are in unit/test_check_result.py."""

import subprocess
import sys

import pytest
from conftest import REPO


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(REPO / "scripts" / "check_result.py"), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_the_script_exits_0_when_check_passes_and_1_when_it_fails() -> None:
    passed = run("skipped", "success", "none")
    failed = run("failure", "success", "full")
    assert (passed.returncode, failed.returncode) == (0, 1)
    assert passed.stdout.startswith("check: passed, ")
    assert failed.stdout.startswith("check: failed, ")


@pytest.mark.parametrize("args", [(), ("success",), ("success", "success", "none", "extra")])
def test_a_wrong_number_of_arguments_fails_naming_what_to_pass(args: tuple[str, ...]) -> None:
    result = run(*args)
    assert result.returncode == 1
    assert f"expected 3 arguments (LEGS CHANGES SCOPE), got {len(args)}" in result.stderr
