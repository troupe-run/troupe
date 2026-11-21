"""The conformance suite, run against the scripted runner and any runner named in the environment.

To check another runner, set TROUPE_CONFORMANCE_RUNNER to its command line as a JSON array, and
TROUPE_CONFORMANCE_OPTIONS to the JSON run/start options for a short run that succeeds. A runner
that needs a runtime is given one by TROUPE_CONFORMANCE_RUNTIME: a JSON object holding the runtime's
name and the fields a runtime has in config, resolved as a run resolves it (built-in, then the
object, then TROUPE_RUNTIME_<NAME>_*). Its credential is named only by the variable that holds it,
whose value goes to the runner as TROUPE_RUNTIME_CREDENTIAL (spec: actor-runners;
conformance-runtime design D1-D3). Unset or empty means absent; anything else malformed is refused.
"""

import asyncio
import json
import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

import anthropic_stand_in
import claude_stand_in
import ollama_stand_in
import openai_stand_in
from troupe.core import defaults, runtimes
from troupe.core.config.kinds import runtime_problems
from troupe.core.errors import TroupeError
from troupe.core.runners.conformance import CheckResult, check_runner
from troupe.core.runners.host import RunnerCommand
from troupe.core.runners.limits import RunLimits
from troupe.platform import processes
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
    credential: str | None = None,
) -> dict[str, CheckResult]:
    results = asyncio.run(
        check_runner(
            RunnerCommand(argv, cwd=workspace, env=env or {}),
            options,
            workspace=workspace,
            limits=limits,
            runtime=runtime,
            credential=credential,
        )
    )
    return {result.name: result for result in results}


RUNNER_VARIABLE = "TROUPE_CONFORMANCE_RUNNER"
OPTIONS_VARIABLE = "TROUPE_CONFORMANCE_OPTIONS"
RUNTIME_VARIABLE = "TROUPE_CONFORMANCE_RUNTIME"
RUNNER_ACCEPTED = "a JSON array of strings, the runner's command line, whose first isn't empty"
OPTIONS_ACCEPTED = "a JSON object, the run/start options for a short run that succeeds"
RUNTIME_ACCEPTED = (
    'a JSON object holding the runtime\'s "name" and the fields a runtime has in config '
    '("endpoint", "model", "credential": {"env": <variable>}, "prices")'
)
ACTOR = "conformance"
"""The actor troupe resolves the runtime for: it names none of its own (design D3)."""


class ConformanceSetupError(ValueError):
    """A conformance variable that is set but malformed: names the variable, what it must hold
    and the fix, and never the value, which for the runtime could hold a key (design D3)."""

    def __init__(self, variable: str, problem: str, accepted: str) -> None:
        super().__init__(f"{variable} {problem}. Set it to {accepted}, or unset it.")


@dataclass(frozen=True)
class Target:
    """What the env-driven check runs: the runner, its options, its runtime and its credential."""

    argv: list[str]
    options: dict[str, Any]
    runtime: RunStartRuntime | None = None
    credential: str | None = field(default=None, repr=False)

    @property
    def env(self) -> dict[str, str]:
        """The runner's own environment entries: the credential, as a run gives it (design D2)."""
        return {"TROUPE_RUNTIME_CREDENTIAL": self.credential} if self.credential else {}


def _json(env: Mapping[str, str], variable: str, accepted: str) -> object:
    """The JSON ``variable`` holds, or None when it's unset or empty."""
    raw = env.get(variable, "")
    if raw == "":
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError as error:
        # The position only: the text could be a key pasted in the wrong place.
        where = f"line {error.lineno} column {error.colno}"
        raise ConformanceSetupError(variable, f"isn't JSON (at {where})", accepted) from None


def _runtime(env: Mapping[str, str]) -> tuple[RunStartRuntime | None, str | None]:
    """The runtime TROUPE_CONFORMANCE_RUNTIME gives, as a run resolves it, and its credential's
    value read from ``env``; (None, None) when it gives none (design D1)."""
    data = _json(env, RUNTIME_VARIABLE, RUNTIME_ACCEPTED)
    if data is None:
        return None, None
    if not isinstance(data, dict):
        raise ConformanceSetupError(RUNTIME_VARIABLE, "isn't a JSON object", RUNTIME_ACCEPTED)
    name = data.get("name")
    if not isinstance(name, str):
        raise ConformanceSetupError(
            RUNTIME_VARIABLE, 'has no "name" that is a string', RUNTIME_ACCEPTED
        )
    entry = {key: value for key, value in data.items() if key != "name"}
    problems = runtime_problems(name, entry)
    if problems:
        found = "; ".join(
            f"{'.'.join(problem.path[2:]) or 'name'}: {problem.rule}" for problem in problems
        )
        raise ConformanceSetupError(
            RUNTIME_VARIABLE, f"breaks a runtime's rules ({found})", RUNTIME_ACCEPTED
        )
    config = {runtimes.RUNTIMES: {name: entry}}
    if runtimes.run_model(runtimes.resolve(name, config, env), None) is None:
        raise ConformanceSetupError(
            RUNTIME_VARIABLE,
            f'sets no "model", and neither does troupe\'s runtime {name!r} or '
            f"{runtimes.env_name(name, 'model')}",
            RUNTIME_ACCEPTED,
        )
    run = runtimes.for_run(name, ACTOR, None, config, env)
    return RunStartRuntime.from_data(run.run_start()), run.value


def conformance_target(env: Mapping[str, str]) -> Target:
    """What ``env``'s TROUPE_CONFORMANCE_* variables name. Raises ConformanceSetup for a malformed
    variable, and the runtime's own refusals (a TroupeError) for its credential (design D3)."""
    argv = _json(env, RUNNER_VARIABLE, RUNNER_ACCEPTED)
    if argv is None:
        raise ConformanceSetupError(RUNNER_VARIABLE, "isn't set", RUNNER_ACCEPTED)
    if (
        not isinstance(argv, list)
        or not argv
        or not all(isinstance(part, str) for part in argv)
        or argv[0] == ""
    ):
        raise ConformanceSetupError(RUNNER_VARIABLE, "isn't a command line", RUNNER_ACCEPTED)
    options = _json(env, OPTIONS_VARIABLE, OPTIONS_ACCEPTED)
    if options is None:
        options = {}
    if not isinstance(options, dict):
        raise ConformanceSetupError(OPTIONS_VARIABLE, "isn't a JSON object", OPTIONS_ACCEPTED)
    runtime, credential = _runtime(env)
    return Target(argv, options, runtime, credential)


def _check_environment(
    env: Mapping[str, str], workspace: Path, limits: RunLimits = LIMITS
) -> dict[str, CheckResult]:
    """The checks for the runner ``env``'s TROUPE_CONFORMANCE_* variables name."""
    target = conformance_target(env)
    return _check(
        target.argv,
        target.options,
        workspace,
        limits,
        target.env,
        target.runtime,
        target.credential,
    )


def _script(*steps: dict[str, Any]) -> dict[str, Any]:
    return {"script": {"steps": list(steps)}}


def test_the_scripted_runner_passes_every_conformance_check(tmp_path: Path) -> None:
    results = _check(
        SCRIPTED, _script({"event": INIT}, {"wait": {"ms": 200}}, {"event": OK}), tmp_path
    )
    failed = {name: r.problem for name, r in results.items() if not r.passed}
    assert failed == {}
    assert len(results) == 9
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


def test_a_runner_that_answers_a_second_initialize_fails_that_check(tmp_path: Path) -> None:
    results = _check([sys.executable, str(FAKE), "ignore-options"], {}, tmp_path, EXPIRING)
    check = results["second initialize refused"]
    assert not check.passed
    assert check.problem is not None
    assert "second initialize" in check.problem
    assert "runner.already-initialized" in check.problem


def test_a_runner_that_counts_a_refused_initialize_as_its_handshake_fails_that_check(
    tmp_path: Path,
) -> None:
    results = _check([sys.executable, str(FAKE), "early-initialized"], {}, tmp_path, EXPIRING)
    check = results["version refusal"]
    assert not check.passed
    assert check.problem is not None
    assert "after one it refused for its versions" in check.problem


def test_a_runner_that_does_not_exit_on_end_of_input_fails_that_check(tmp_path: Path) -> None:
    results = _check([sys.executable, str(FAKE), "ignore-eof"], {}, tmp_path, EXPIRING)
    check = results["exit on end of input"]
    assert not check.passed
    assert check.problem is not None
    assert "input closing" in check.problem


@pytest.mark.skipif(
    not os.environ.get(RUNNER_VARIABLE),
    reason="opt-in: set TROUPE_CONFORMANCE_RUNNER (and TROUPE_CONFORMANCE_OPTIONS, and "
    "TROUPE_CONFORMANCE_RUNTIME for a runner that needs a runtime) to check another runner",
)
def test_the_runner_named_in_the_environment_passes_every_conformance_check(
    tmp_path: Path,
) -> None:
    results = _check_environment(os.environ, tmp_path)
    assert {name: r.problem for name, r in results.items() if not r.passed} == {}


def test_a_runner_that_refuses_a_character_fails_that_check(tmp_path: Path) -> None:
    results = _check([sys.executable, str(FAKE), "refuse-character"], {}, tmp_path, EXPIRING)
    check = results["run/start with a character accepted"]
    assert not check.passed
    assert check.problem is not None
    assert "refused run/start" in check.problem


def test_a_credential_a_runner_echoes_in_a_refusal_is_masked_in_every_check(tmp_path: Path) -> None:
    # Spec: actor-runners, "The conformance suite masks the credential in every check"
    # (conformance-runtime D4).
    key = "sk-echoed-0123456789"
    results = asyncio.run(
        check_runner(
            RunnerCommand(
                [sys.executable, str(FAKE), "refuse-with-credential"],
                cwd=tmp_path,
                env={"TROUPE_RUNTIME_CREDENTIAL": key},
            ),
            {},
            workspace=tmp_path,
            limits=EXPIRING,
            runtime=RunStartRuntime(
                name="test", endpoint="http://127.0.0.1:9", model="m", credential=True
            ),
            credential=key,
        )
    )
    refused = [r for r in results if r.problem and "refused the key" in r.problem]
    assert refused, [r.problem for r in results]
    assert all("refused the key [credential]" in (r.problem or "") for r in refused)
    assert not [r.name for r in results if key in (r.problem or "")]


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
    assert len(results) == 9


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
    assert len(results) == 9


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
    assert len(results) == 9


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
    assert len(results) == 9


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
    assert len(results) == 9


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


# Requirement: The conformance suite can be given a runtime through the environment, takes a
# credential only by reference, and refuses a malformed variable (conformance-runtime D1-D3).

SCRIPTED_ENV = {RUNNER_VARIABLE: json.dumps(SCRIPTED)}
KEY = "sk-conformance-env-0123456789"
JSON_VALUES = st.recursive(
    st.none() | st.booleans() | st.integers() | st.text(),
    lambda inner: st.lists(inner, max_size=3) | st.dictionaries(st.text(), inner, max_size=3),
    max_leaves=8,
)


@given(st.dictionaries(st.text(), JSON_VALUES, max_size=4))
def test_options_set_to_a_json_object_are_read_as_json_reads_them(options: dict[str, Any]) -> None:
    # The rule before this change: the options were json.loads of the variable.
    env = {**SCRIPTED_ENV, OPTIONS_VARIABLE: json.dumps(options)}
    assert conformance_target(env).options == options


@given(st.lists(st.text(), min_size=1, max_size=4).filter(lambda argv: argv[0] != ""))
def test_a_runner_set_to_a_json_array_of_strings_is_read_as_json_reads_it(argv: list[str]) -> None:
    assert conformance_target({RUNNER_VARIABLE: json.dumps(argv)}).argv == argv


@pytest.mark.parametrize("options", [None, ""])
def test_options_unset_or_empty_are_no_options(options: str | None) -> None:
    env = dict(SCRIPTED_ENV) if options is None else {**SCRIPTED_ENV, OPTIONS_VARIABLE: options}
    assert conformance_target(env).options == {}


@pytest.mark.parametrize("runtime", [None, ""])
def test_a_runtime_unset_or_empty_sends_no_runtime_and_no_credential(runtime: str | None) -> None:
    env = dict(SCRIPTED_ENV) if runtime is None else {**SCRIPTED_ENV, RUNTIME_VARIABLE: runtime}
    target = conformance_target(env)
    assert (target.runtime, target.credential, target.env) == (None, None, {})


def test_a_built_in_runtime_by_name_resolves_as_a_run_resolves_it() -> None:
    env = {
        **SCRIPTED_ENV,
        RUNTIME_VARIABLE: json.dumps({"name": "openai", "model": "fake-model"}),
        "TROUPE_RUNTIME_OPENAI_ENDPOINT": "http://127.0.0.1:9/v1",
        "OPENAI_API_KEY": KEY,
    }
    target = conformance_target(env)
    assert target.runtime == RunStartRuntime(
        name="openai", endpoint="http://127.0.0.1:9/v1", model="fake-model", credential=True
    )
    assert target.credential == KEY


def test_an_outside_runners_own_runtime_is_sent_as_given() -> None:
    runtime = {"name": "my-service", "endpoint": "https://api.example.test/v2", "model": "small"}
    target = conformance_target({**SCRIPTED_ENV, RUNTIME_VARIABLE: json.dumps(runtime)})
    assert target.runtime == RunStartRuntime(
        name="my-service", endpoint="https://api.example.test/v2", model="small", credential=False
    )
    assert (target.credential, target.env) == (None, {})


def test_the_runners_environment_holds_the_credential_as_troupe_runtime_credential_not_its_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = {
        "name": "my-service",
        "endpoint": "https://api.example.test",
        "model": "small",
        "credential": {"env": "MY_SERVICE_KEY"},
    }
    monkeypatch.setenv("MY_SERVICE_KEY", KEY)
    target = conformance_target(
        {**SCRIPTED_ENV, RUNTIME_VARIABLE: json.dumps(runtime), **os.environ}
    )
    # The runner's environment, built as check_runner builds it for every check.
    runner_env = processes.build_environment(defaults.RUNNER_ENVIRONMENT, explicit=target.env)
    assert runner_env["TROUPE_RUNTIME_CREDENTIAL"] == KEY
    assert "MY_SERVICE_KEY" not in runner_env
    assert KEY not in repr(target)


def test_a_credential_whose_variable_isnt_set_is_refused_naming_it() -> None:
    runtime = {"name": "openai", "model": "m", "credential": {"env": "NOT_SET_ANYWHERE"}}
    with pytest.raises(TroupeError) as raised:
        conformance_target({**SCRIPTED_ENV, RUNTIME_VARIABLE: json.dumps(runtime)})
    assert raised.value.code == "runtime.credential-unset"
    assert "NOT_SET_ANYWHERE" in raised.value.problem


def test_a_credential_over_plain_http_to_another_host_is_refused() -> None:
    runtime = {
        "name": "my-service",
        "endpoint": "http://api.example.test",
        "model": "m",
        "credential": {"env": "MY_SERVICE_KEY"},
    }
    env = {**SCRIPTED_ENV, RUNTIME_VARIABLE: json.dumps(runtime), "MY_SERVICE_KEY": KEY}
    with pytest.raises(TroupeError) as raised:
        conformance_target(env)
    assert raised.value.code == "runtime.insecure-endpoint"
    assert KEY not in str(raised.value.to_data())


def test_a_key_put_where_the_credentials_name_goes_is_refused_without_repeating_it() -> None:
    runtime = {"name": "openai", "model": "m", "credential": {"env": "sk-proj-abc 0123456789"}}
    with pytest.raises(ConformanceSetupError) as raised:
        conformance_target({**SCRIPTED_ENV, RUNTIME_VARIABLE: json.dumps(runtime)})
    message = str(raised.value)
    assert RUNTIME_VARIABLE in message
    assert "credential.env" in message
    assert "sk-proj" not in message


def test_a_runtime_that_isnt_json_is_refused_without_repeating_it() -> None:
    with pytest.raises(ConformanceSetupError) as raised:
        conformance_target({**SCRIPTED_ENV, RUNTIME_VARIABLE: "sk-pasted-0123456789"})
    assert RUNTIME_VARIABLE in str(raised.value)
    assert "sk-pasted" not in str(raised.value)


def test_a_runtime_with_a_field_config_doesnt_have_is_refused_naming_it() -> None:
    runtime = {"name": "openai", "model": "m", "api_key_env": "X"}
    with pytest.raises(ConformanceSetupError) as raised:
        conformance_target({**SCRIPTED_ENV, RUNTIME_VARIABLE: json.dumps(runtime)})
    assert RUNTIME_VARIABLE in str(raised.value)
    assert "api_key_env" in str(raised.value)


def test_a_runtime_with_no_model_anywhere_is_refused_naming_where_one_goes() -> None:
    with pytest.raises(ConformanceSetupError) as raised:
        conformance_target({**SCRIPTED_ENV, RUNTIME_VARIABLE: json.dumps({"name": "ollama"})})
    assert '"model"' in str(raised.value)
    assert "TROUPE_RUNTIME_OLLAMA_MODEL" in str(raised.value)


@pytest.mark.parametrize("options", ["[]", '"x"', "{"])
def test_options_that_arent_a_json_object_are_refused_naming_the_variable(options: str) -> None:
    with pytest.raises(ConformanceSetupError) as raised:
        conformance_target({**SCRIPTED_ENV, OPTIONS_VARIABLE: options})
    assert OPTIONS_VARIABLE in str(raised.value)
    assert "a JSON object" in str(raised.value)


@pytest.mark.parametrize("runner", ["", "python", "[]", '[""]', '["a", 1]', '{"a": 1}'])
def test_a_runner_that_isnt_a_command_line_is_refused_naming_the_variable(runner: str) -> None:
    with pytest.raises(ConformanceSetupError) as raised:
        conformance_target({RUNNER_VARIABLE: runner})
    assert RUNNER_VARIABLE in str(raised.value)
    assert "a JSON array of strings" in str(raised.value)


def test_the_env_driven_check_passes_the_openai_runner_given_a_runtime_and_a_credential(
    tmp_path: Path,
) -> None:
    # #299's case: with no runtime, 5 of 8 checks failed with openai.no-runtime (design D5).
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    with openai_stand_in.serving([openai_stand_in.text_reply("Done.")] * 20) as fake:
        env = {
            RUNNER_VARIABLE: json.dumps([sys.executable, "-m", "troupe_runner_openai"]),
            OPTIONS_VARIABLE: json.dumps(openai_stand_in.TEST_LIMITS),
            RUNTIME_VARIABLE: json.dumps(
                {"name": "openai", "model": "fake-model", "credential": {"env": "MY_OPENAI_KEY"}}
            ),
            "TROUPE_RUNTIME_OPENAI_ENDPOINT": fake.endpoint,
            "MY_OPENAI_KEY": KEY,
        }
        results = _check_environment(
            env, workspace, RunLimits(start_timeout=10.0, cancel_grace=10.0, run_timeout=30.0)
        )
        assert fake.requests
        assert {r.headers["authorization"] for r in fake.requests} == {f"Bearer {KEY}"}
    assert {name: r.problem for name, r in results.items() if not r.passed} == {}
    assert len(results) == 9
