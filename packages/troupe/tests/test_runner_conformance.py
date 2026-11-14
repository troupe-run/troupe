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

import anthropic_stand_in
import claude_stand_in
import lm_studio_stand_in
import ollama_stand_in
import openai_stand_in
from troupe.core.runners.conformance import CheckResult, check_runner
from troupe.core.runners.host import RunnerCommand
from troupe.core.runners.limits import RunLimits
from troupe_plugin_sdk.runner import RunStartRuntime

SCRIPTED = [sys.executable, "-m", "troupe_runner_scripted"]
FAKE = Path(__file__).with_name("fake_runner.py")
INIT = {
    "type": "init",
    "runner": {"name": "scripted", "version": "0.0.1"},
    "effects": "checked",
    "tools": [],
}
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
    argv: list[str],
    options: dict[str, Any],
    workspace: Path,
    limits: RunLimits = LIMITS,
    env: dict[str, str] | None = None,
    runtime: RunStartRuntime | None = None,
) -> dict[str, CheckResult]:
    results = asyncio.run(
        check_runner(
            RunnerCommand(argv, cwd=workspace, env=env or {}),
            options,
            workspace=workspace,
            limits=limits,
            runtime=runtime,
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
    assert len(results) == 8
    assert "run/start with a character accepted" in results


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


def test_a_runner_that_refuses_a_character_fails_that_check(tmp_path: Path) -> None:
    results = _check([sys.executable, str(FAKE), "refuse-character"], {}, tmp_path, EXPIRING)
    check = results["run/start with a character accepted"]
    assert not check.passed
    assert check.problem is not None
    assert "refused run/start" in check.problem


def test_the_claude_code_runner_passes_every_check_with_a_stand_in_claude(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    claude_stand_in.install(
        bin_dir, fixture=claude_stand_in.fixture("success-with-tools"), wait_ms="200"
    )
    env = {"PATH": str(bin_dir)}
    env.update(
        {
            n: os.environ[n]
            for n in ("COMSPEC", "PATHEXT", "TEMP", "TMP", "TMPDIR")
            if n in os.environ
        }
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    results = _check(
        [sys.executable, "-m", "troupe_runner_claude_code"],
        {},
        workspace,
        RunLimits(start_timeout=10.0, cancel_grace=10.0, run_timeout=30.0),
        env,
    )
    assert {name: r.problem for name, r in results.items() if not r.passed} == {}
    assert len(results) == 8


def test_the_ollama_runner_passes_every_check_given_a_runtime_naming_a_stand_in(
    tmp_path: Path,
) -> None:
    # Spec: ollama-runner, "The runner conforms to the contract" (local-model-runner task 8.3,
    # ollama-uses-runtime D7).
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    with ollama_stand_in.answering(count=20, delay=0.2) as fake:
        results = _check(
            [sys.executable, "-m", "troupe_runner_ollama"],
            {},
            workspace,
            RunLimits(start_timeout=10.0, cancel_grace=10.0, run_timeout=30.0),
            {},
            RunStartRuntime(name="test", endpoint=fake.url, model="fake", credential=False),
        )
    assert {name: r.problem for name, r in results.items() if not r.passed} == {}
    assert len(results) == 8


def test_the_openai_style_runner_passes_every_check_given_a_runtime_naming_a_stand_in(
    tmp_path: Path,
) -> None:
    # Spec: openai-runner, "The runner conforms to the contract" (openai-style-runner 8.2).
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    key = "sk-conformance-0123456789"
    with openai_stand_in.serving([openai_stand_in.text_reply("Done.")] * 20) as fake:
        runtime = RunStartRuntime(
            name="test", endpoint=fake.endpoint, model="fake-model", credential=True
        )
        results = asyncio.run(
            check_runner(
                RunnerCommand(
                    [sys.executable, "-m", "troupe_runner_openai"],
                    cwd=workspace,
                    env={"TROUPE_RUNTIME_CREDENTIAL": key},
                ),
                openai_stand_in.TEST_LIMITS,
                workspace=workspace,
                limits=RunLimits(start_timeout=10.0, cancel_grace=10.0, run_timeout=30.0),
                runtime=runtime,
                credential=key,
            )
        )
        assert fake.requests
        assert {r.headers["authorization"] for r in fake.requests} == {f"Bearer {key}"}
    assert {r.name: r.problem for r in results if not r.passed} == {}
    assert len(results) == 8


def test_the_anthropic_runner_passes_every_check_given_a_runtime_naming_a_stand_in(
    tmp_path: Path,
) -> None:
    # Spec: anthropic-runner, "The runner conforms to the contract" (anthropic-runner task 12.2).
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    key = "sk-ant-conformance-0123456789"
    with anthropic_stand_in.serving([anthropic_stand_in.text_reply("Done.")] * 20) as fake:
        runtime = RunStartRuntime(
            name="test", endpoint=fake.endpoint, model="fake-model", credential=True
        )
        results = asyncio.run(
            check_runner(
                RunnerCommand(
                    [sys.executable, "-m", "troupe_runner_anthropic"],
                    cwd=workspace,
                    env={"TROUPE_RUNTIME_CREDENTIAL": key},
                ),
                anthropic_stand_in.TEST_LIMITS,
                workspace=workspace,
                limits=RunLimits(start_timeout=10.0, cancel_grace=10.0, run_timeout=30.0),
                runtime=runtime,
                credential=key,
            )
        )
        assert fake.requests
        assert {r.headers["authorization"] for r in fake.requests} == {f"Bearer {key}"}
    assert {r.name: r.problem for r in results if not r.passed} == {}
    assert len(results) == 8


def test_the_lm_studio_runner_passes_every_check_given_a_runtime_naming_a_stand_in(
    tmp_path: Path,
) -> None:
    # Spec: lm-studio-runner, "The runner conforms to the contract" (lmstudio-runner task 10.2).
    # Each check starts its own run, and some cancel theirs part-way, so the stand-in answers every
    # request by its kind; each run is slow enough for the checks that cancel one mid-run.
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    with lm_studio_stand_in.serving(text=" ".join(["word"] * 40), pause=0.05) as fake:
        results = _check(
            [sys.executable, "-m", "troupe_runner_lm_studio"],
            dict(lm_studio_stand_in.TEST_LIMITS),
            workspace,
            RunLimits(start_timeout=10.0, cancel_grace=10.0, run_timeout=30.0),
            {},
            RunStartRuntime(
                name="test",
                endpoint=fake.endpoint,
                model=lm_studio_stand_in.MODEL,
                credential=False,
            ),
        )
    assert {name: r.problem for name, r in results.items() if not r.passed} == {}
    assert len(results) == 8


def test_the_mistralrs_runner_passes_every_check_with_the_engine_stand_in(tmp_path: Path) -> None:
    # Spec: mistralrs-runner, "The runner conforms to the contract" (in-process-runner task 9.1).
    # Each check starts its own runner process, which reads the stand-in's script afresh; each
    # answer takes a moment, so the checks that cancel a run part-way find it running.
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    plugin = Path(__file__).resolve().parents[3] / "plugins" / "runner-mistralrs"
    glob = {
        "id": "c",
        "type": "function",
        "function": {"name": "Glob", "arguments": '{"pattern": "*"}'},
    }

    def answer(message: dict[str, Any], finish: str) -> dict[str, Any]:
        return {
            "id": "1",
            "object": "chat.completion",
            "created": 0,
            "model": "mistralrs",
            "system_fingerprint": "local",
            "choices": [{"index": 0, "finish_reason": finish, "message": message}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 5, "total_tokens": 105},
            "delay": 0.3,
        }

    calls = [answer({"role": "assistant", "content": "", "tool_calls": [glob]}, "tool_calls")]
    done = answer({"role": "assistant", "content": "Done."}, "stop")
    script = tmp_path / "script.json"
    script.write_text(json.dumps({"responses": [*calls * 3, done]}), encoding="utf-8")
    results = _check(
        [sys.executable, str(plugin / "tests" / "stand_in_runner.py")],
        {},
        workspace,
        RunLimits(start_timeout=10.0, cancel_grace=10.0, run_timeout=30.0),
        {"TROUPE_MISTRALRS_STAND_IN": str(script)},
        RunStartRuntime(
            name="mistralrs",
            model=str(
                plugin / "src" / "troupe_runner_mistralrs" / "check_model" / "stories260K.gguf"
            ),
            credential=False,
        ),
    )
    assert {name: r.problem for name, r in results.items() if not r.passed} == {}
    assert len(results) == 8


# Requirement: Any conforming runner can be checked: init says how the runner applies the effects
# (declared-effects)


def test_a_runner_whose_init_doesnt_say_how_it_applies_the_effects_fails_the_whole_run_check(
    tmp_path: Path,
) -> None:
    results = _check([sys.executable, str(FAKE), "init-without-effects"], {}, tmp_path, EXPIRING)
    check = results["a whole run: init first, seq, result, shutdown"]
    assert not check.passed
    assert check.problem is not None
    assert "InitEvent" in check.problem
    assert "effects" in check.problem
