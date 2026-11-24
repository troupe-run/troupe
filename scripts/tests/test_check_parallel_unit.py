"""The tests gate's settings that run_gates relies on: the full and the scoped tests gates ask for
the slowest tests' durations, and pyproject.toml sets a stall limit above the slowest test and
within the CI job's room (spec: quality-check; parallel-tests design D1-D3; shorten-slow-tests
design D4; windows-ci-hang design D1).

Its tests that start a process, open a socket or use a git theatre are in
integration/test_check_parallel.py."""

import tomllib
from pathlib import Path

import check


def test_the_full_and_the_scoped_tests_gates_ask_for_the_slowest_durations() -> None:
    for scopes in [(), ("docs",)]:
        tests = dict(check.gates(scopes))["tests"]
        assert tests[1 : 1 + len(check.PARALLEL) + 1] == [*check.PARALLEL, "--durations=25"]


SLOWEST_TEST_MARGIN = 120
"""The stall limit must be above this many seconds: the slowest test takes 87 s on Windows CI."""
STALL_LIMIT_CEILING = 600
"""...and at most this many: the CI job's 30 minutes, less a Windows leg of up to 20 minutes."""


def test_the_repositorys_stall_limit_is_set_above_the_slowest_test_and_below_the_jobs_room() -> (
    None
):
    pyproject = Path(check.ROOT, "pyproject.toml").read_text(encoding="utf-8")
    options = tomllib.loads(pyproject)["tool"]["pytest"]["ini_options"]

    assert "faulthandler_timeout" in options, "pyproject.toml sets no stall limit"
    assert SLOWEST_TEST_MARGIN < options["faulthandler_timeout"] <= STALL_LIMIT_CEILING
