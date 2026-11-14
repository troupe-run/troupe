"""Warming a runner's engine outside any run, and troupe init --audition doing it once (spec: cli,
"Init with an audition warms its runner's engine"; in-process-runner design D4; owner, 2026-11-14).

Each case stands a small Python script in for the runner, saying what a real warm-up would.
"""

import dataclasses
import json
import sys
from pathlib import Path

import pytest

from protocol_schemas import check_notice
from troupe.core import interim
from troupe.core.runners.warm_up import warm_up


def _runner(monkeypatch: pytest.MonkeyPatch, script: str, warm: tuple[str, ...] = ("go",)) -> None:
    """Make the mistralrs runner a script that, given ``warm``, runs ``script``."""
    entry = dataclasses.replace(
        interim.RUNNERS["mistralrs"], command=(sys.executable, "-c", script), warm_up=warm
    )
    monkeypatch.setitem(interim.RUNNERS, "mistralrs", entry)


def _say(answer: object, code: int = 0) -> str:
    return f"import json, sys; print(json.dumps({answer!r})); sys.exit({code})"


def test_a_warmed_up_engine_is_a_notice_with_how_long_it_took(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _runner(monkeypatch, _say({"warmedUp": True, "seconds": 17.3}))
    (notice,) = warm_up("mistralrs", tmp_path, {})
    assert notice.code == "runner.warmed-up"
    assert notice.details == {"runner": "mistralrs", "seconds": 17.3}
    assert "17.3s" in notice.problem
    check_notice(notice.to_data())


def test_nothing_to_warm_on_this_platform_is_no_notice(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _runner(monkeypatch, _say({"warmedUp": False}))
    assert warm_up("mistralrs", tmp_path, {}) == []


def test_a_runner_without_a_warm_up_starts_no_process(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _runner(monkeypatch, "raise SystemExit('started')", warm=())
    assert warm_up("mistralrs", tmp_path, {}) == []


def test_a_runner_that_cant_run_here_says_so_with_its_own_problem_and_fix(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    problem = "mistral.rs can't compile its Metal kernels under this Python."
    error: dict[str, object] = {
        "code": "mistralrs.unsupported-python",
        "problem": problem,
        "fix": "Install troupe on a uv-managed Python.",
        "details": {"python": "/opt/homebrew/bin/python3.15", "version": "3.15.2"},
    }
    _runner(monkeypatch, _say({"error": error}, code=1))
    (notice,) = warm_up("mistralrs", tmp_path, {})
    assert notice.code == "runner.warm-up-failed"
    assert notice.details == {"runner": "mistralrs", "code": "mistralrs.unsupported-python"}
    assert problem in notice.problem
    assert notice.fix == error["fix"]
    check_notice(notice.to_data())


def test_a_warm_up_that_says_nothing_it_can_read_is_a_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _runner(monkeypatch, "print('not json'); raise SystemExit(3)")
    (notice,) = warm_up("mistralrs", tmp_path, {})
    assert notice.code == "runner.warm-up-failed"
    assert "exited 3" in notice.problem


def test_a_warm_up_past_its_limit_is_stopped_and_its_first_run_finishes_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _runner(monkeypatch, "import time; time.sleep(60)")
    (notice,) = warm_up("mistralrs", tmp_path, {}, timeout=0.5)
    assert notice.code == "runner.warm-up-cut-off"
    assert notice.details == {"runner": "mistralrs", "seconds": 0.5}
    assert "perform it again" in notice.fix
    check_notice(notice.to_data())


def test_the_warm_up_gets_the_runners_environment_and_no_more(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    script = (
        "import json, os; print(json.dumps({'warmedUp': True, "
        "'seconds': float('TROUPE_CANARY' in os.environ)}))"
    )
    _runner(monkeypatch, script)
    (notice,) = warm_up("mistralrs", tmp_path, {"TROUPE_CANARY": "x"})
    assert notice.details["seconds"] == 0  # the canary didn't reach it


def test_the_mistralrs_runner_warms_with_its_own_argument() -> None:
    assert interim.RUNNERS["mistralrs"].warm_up == ("--warm-up",)
    assert all(not entry.warm_up for name, entry in interim.RUNNERS.items() if name != "mistralrs")


def test_the_real_mistralrs_runners_warm_up_answers_in_one_line(tmp_path: Path) -> None:
    notices = warm_up("mistralrs", tmp_path, {})
    if sys.platform == "darwin":
        (notice,) = notices
        assert notice.code == "runner.warmed-up", notice.problem
    else:
        assert notices == []
    assert json.dumps([n.to_data() for n in notices])
