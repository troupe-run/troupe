"""How the conformance suite reads the runner it checks from the environment:
TROUPE_CONFORMANCE_RUNNER as a JSON array command line, TROUPE_CONFORMANCE_OPTIONS as JSON
run/start options, and TROUPE_CONFORMANCE_RUNTIME as a JSON object resolved as a run resolves a
runtime, whose credential is named only by the variable that holds it and reaches the runner as
TROUPE_RUNTIME_CREDENTIAL. Unset or empty means absent, and anything else malformed is refused,
naming the variable and never repeating a key (spec: actor-runners; conformance-runtime design
D1-D3).

Its tests that start a process, open a socket or use a git theatre are in
integration/test_runner_conformance_integration.py."""

import json
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from runner_conformance_shared import (
    KEY,
    OPTIONS_VARIABLE,
    RUNNER_VARIABLE,
    RUNTIME_VARIABLE,
    SCRIPTED,
    ConformanceSetupError,
    conformance_target,
)
from troupe.core import defaults
from troupe.core.errors import TroupeError
from troupe.platform import processes
from troupe_plugin_sdk.runner import RunStartRuntime

# Requirement: The conformance suite can be given a runtime through the environment, takes a
# credential only by reference, and refuses a malformed variable (conformance-runtime D1-D3).

SCRIPTED_ENV = {RUNNER_VARIABLE: json.dumps(SCRIPTED)}
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
    target = conformance_target(
        {**SCRIPTED_ENV, RUNTIME_VARIABLE: json.dumps(runtime), "MY_SERVICE_KEY": KEY}
    )
    # In the real environment too, so the check shows the runner's isn't given it from there.
    monkeypatch.setenv("MY_SERVICE_KEY", KEY)
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
