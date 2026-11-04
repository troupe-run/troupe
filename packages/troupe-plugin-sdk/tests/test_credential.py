"""Where a runner finds its run's credential (spec: runner-protocol, "The credential's value is in
the runner's environment as TROUPE_RUNTIME_CREDENTIAL")."""

from dataclasses import replace

import pytest

from troupe_plugin_sdk.credential import CredentialError, runtime_credential
from troupe_plugin_sdk.runner import (
    READ_ONLY_DECLARATION,
    RunStartParams,
    RunStartRuntime,
    StartLimits,
)

PARAMS = RunStartParams(
    run_id="0f8fad5b-d9cb-469f-a165-70867728950e",
    direction="",
    workspace="/w",
    options={},
    limits=StartLimits(event_max_bytes=1000),
    effects=READ_ONLY_DECLARATION,
    scratch="/s",
)
RUNTIME = RunStartRuntime(
    name="openai", endpoint="https://api.openai.com/v1", model="gpt-test", credential=True
)
KEY = "sk-test-0123456789"


def test_a_runtime_with_a_credential_gives_its_value() -> None:
    params = replace(PARAMS, runtime=RUNTIME)
    assert runtime_credential(params, {"TROUPE_RUNTIME_CREDENTIAL": KEY}) == KEY


@pytest.mark.parametrize(
    "params",
    [
        pytest.param(PARAMS, id="no runtime"),
        pytest.param(replace(PARAMS, runtime=replace(RUNTIME, credential=False)), id="none"),
    ],
)
def test_a_run_without_a_credential_gives_none(params: RunStartParams) -> None:
    assert runtime_credential(params, {}) is None


@pytest.mark.parametrize("environ", [{}, {"TROUPE_RUNTIME_CREDENTIAL": ""}], ids=["unset", "empty"])
def test_a_credential_run_start_promises_but_the_environment_lacks_is_refused(
    environ: dict[str, str],
) -> None:
    with pytest.raises(CredentialError, match="isn't set"):
        runtime_credential(replace(PARAMS, runtime=RUNTIME), environ)


def test_a_credential_run_start_doesnt_promise_is_refused_without_naming_its_value() -> None:
    with pytest.raises(CredentialError, match="says the run has no credential") as raised:
        runtime_credential(PARAMS, {"TROUPE_RUNTIME_CREDENTIAL": KEY})
    assert KEY not in str(raised.value)


def test_run_start_reads_its_runtime_and_refuses_one_with_a_value() -> None:
    data = {**PARAMS.to_data(), "runtime": RUNTIME.to_data()}
    assert RunStartParams.from_data(data).runtime == RUNTIME
    with pytest.raises(Exception, match="value"):
        RunStartParams.from_data({**data, "runtime": {**RUNTIME.to_data(), "value": KEY}})
