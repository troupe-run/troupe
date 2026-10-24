"""The interim runner table (perform-status-logs design D4): a name is the only way to a runner."""

import asyncio
from pathlib import Path

import pytest

from troupe.core.errors import TroupeError
from troupe.core.interim import RUNNERS, runner_command
from troupe.core.runners.conformance import check_runner
from troupe.core.runners.host import RunnerCommand
from troupe.core.runners.limits import RunLimits

INIT = {"type": "init", "runner": {"name": "scripted", "version": "0.0.1"}, "tools": []}
OK = {"type": "result", "status": "ok", "message": "done"}


def test_scripted_resolves_to_a_runner_that_passes_every_conformance_check(tmp_path: Path) -> None:
    argv = list(runner_command("scripted"))
    options = {"script": {"steps": [{"event": INIT}, {"wait": {"ms": 200}}, {"event": OK}]}}
    results = asyncio.run(
        check_runner(
            RunnerCommand(argv, cwd=tmp_path),
            options,
            workspace=tmp_path,
            limits=RunLimits(start_timeout=10.0, cancel_grace=3.0, run_timeout=10.0),
        )
    )
    assert {r.name: r.problem for r in results if not r.passed} == {}


def test_an_unknown_runner_fails_naming_the_runners_troupe_knows() -> None:
    with pytest.raises(TroupeError) as caught:
        runner_command("claude")
    assert caught.value.code == "runner.unknown"
    assert "'claude'" in caught.value.problem
    assert caught.value.details == {"runner": "claude", "known": sorted(RUNNERS)}
    assert "scripted" in caught.value.fix


def test_claude_code_resolves_to_the_claude_code_runners_module() -> None:
    assert list(runner_command("claude-code"))[1:] == ["-m", "troupe_runner_claude_code"]


def test_an_unknown_runner_is_refused_naming_both_runners_troupe_ships() -> None:
    with pytest.raises(TroupeError) as caught:
        runner_command("codex")
    assert caught.value.details == {"runner": "codex", "known": ["claude-code", "scripted"]}
    assert "claude-code, scripted" in caught.value.fix
