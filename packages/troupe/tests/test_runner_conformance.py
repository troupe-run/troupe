"""The conformance suite, run against the scripted runner and any runner named in the environment.

To check another runner, set TROUPE_CONFORMANCE_RUNNER to its command line as a JSON array, and
TROUPE_CONFORMANCE_OPTIONS to the JSON run/start options for a short run that succeeds.
"""

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest

from troupe.core.runners.conformance import CheckResult, check_runner
from troupe.core.runners.host import RunnerCommand
from troupe.core.runners.limits import RunLimits

SCRIPTED = [sys.executable, "-m", "troupe_runner_scripted"]
FAKE = Path(__file__).with_name("fake_runner.py")
INIT = {"type": "init", "runner": {"name": "scripted", "version": "0.0.1"}, "tools": []}
OK = {"type": "result", "status": "ok", "message": "done"}
LIMITS = RunLimits(start_timeout=10.0, cancel_grace=3.0, run_timeout=10.0)
"""Generous limits, for checks a runner must pass in time: a real Python runner has to exit within
the grace on a loaded Windows worker (shorten-slow-tests design D1)."""

EXPIRING = RunLimits(start_timeout=10.0, cancel_grace=1.0, run_timeout=1.0)
"""Short limits, for fake runners whose checks fail by waiting a limit out: a shorter wait can't
make such a check pass, and these runners never send a result, so the whole run waits out
run_timeout. start_timeout stays generous, because the checks asserted here fail on what the
runner answers, not on how long it takes (design D1)."""


def _check(
    argv: list[str], options: dict[str, Any], workspace: Path, limits: RunLimits = LIMITS
) -> dict[str, CheckResult]:
    results = asyncio.run(
        check_runner(
            RunnerCommand(argv, cwd=workspace), options, workspace=workspace, limits=limits
        )
    )
    return {result.name: result for result in results}


def _script(*steps: dict[str, Any]) -> dict[str, Any]:
    return {"script": {"steps": list(steps)}}


def test_the_scripted_runner_passes_every_conformance_check(tmp_path: Path) -> None:
    results = _check(
        SCRIPTED, _script({"event": INIT}, {"wait": {"ms": 200}}, {"event": OK}), tmp_path
    )
    failed = {name: r.problem for name, r in results.items() if not r.passed}
    assert failed == {}
    assert len(results) == 7


def test_a_runner_whose_run_has_no_init_fails_the_whole_run_check(tmp_path: Path) -> None:
    results = _check(SCRIPTED, _script({"event": {**OK, "seq": 0}}), tmp_path)
    check = results["a whole run: init first, seq, result, shutdown"]
    assert not check.passed
    assert check.problem is not None
    assert "not 'init'" in check.problem


def test_a_runner_with_a_seq_gap_fails_the_whole_run_check(tmp_path: Path) -> None:
    results = _check(SCRIPTED, _script({"event": INIT}, {"event": {**OK, "seq": 2}}), tmp_path)
    check = results["a whole run: init first, seq, result, shutdown"]
    assert not check.passed
    assert check.problem is not None
    assert "should have been 1" in check.problem


def test_a_runner_that_ignores_an_unknown_option_fails_that_check(tmp_path: Path) -> None:
    results = _check([sys.executable, str(FAKE), "ignore-options"], {}, tmp_path, EXPIRING)
    check = results["unknown option refused"]
    assert not check.passed
    assert check.problem is not None
    assert "troupeConformanceUnknownOption" in check.problem


def test_a_runner_that_does_not_exit_on_end_of_input_fails_that_check(tmp_path: Path) -> None:
    results = _check([sys.executable, str(FAKE), "ignore-eof"], {}, tmp_path, EXPIRING)
    check = results["exit on end of input"]
    assert not check.passed
    assert check.problem is not None
    assert "input closing" in check.problem


@pytest.mark.skipif(
    "TROUPE_CONFORMANCE_RUNNER" not in os.environ,
    reason="opt-in: set TROUPE_CONFORMANCE_RUNNER (and TROUPE_CONFORMANCE_OPTIONS) to check "
    "another runner",
)
def test_the_runner_named_in_the_environment_passes_every_conformance_check(
    tmp_path: Path,
) -> None:
    argv = json.loads(os.environ["TROUPE_CONFORMANCE_RUNNER"])
    options = json.loads(os.environ.get("TROUPE_CONFORMANCE_OPTIONS", "{}"))
    results = _check(argv, options, tmp_path)
    assert {name: r.problem for name, r in results.items() if not r.passed} == {}
