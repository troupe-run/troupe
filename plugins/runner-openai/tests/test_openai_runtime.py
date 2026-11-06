"""The runtime the runner talks to, read from run/start (spec: openai-runner, "The service
comes from the run's runtime", "The credential is read from TROUPE_RUNTIME_CREDENTIAL", "A
credential never travels in the clear"; design D2, D11)."""

import uuid
from typing import Any

import pytest

from openai_harness import own_validator
from troupe_plugin_sdk.runner import RunStartParams
from troupe_runner_openai.runtime import Runtime, RuntimeRefusedError, from_run_start

KEY = "sk-canary-0123456789"


def test_plain_http_to_another_host_with_a_credential_is_refused_naming_the_endpoint() -> None:
    with pytest.raises(RuntimeRefusedError) as raised:
        Runtime.checked("http://models.example.com/v1", "m", KEY)
    assert raised.value.code == "openai.insecure-endpoint"
    assert raised.value.details == {"endpoint": "http://models.example.com/v1"}
    assert "https" in raised.value.fix


@pytest.mark.parametrize(
    ("endpoint", "credential"),
    [
        ("http://127.0.0.1:11434/v1", KEY),
        ("http://localhost:1234/v1", KEY),
        ("https://api.openai.com/v1", KEY),
        ("http://models.example.com/v1", None),
        ("http://models.example.com/v1", ""),
    ],
)
def test_https_this_machine_or_no_credential_is_a_runtime(
    endpoint: str, credential: str | None
) -> None:
    runtime = Runtime.checked(endpoint, "m", credential)
    assert runtime.endpoint.url == endpoint
    assert runtime.credential == (credential or None)


@pytest.mark.parametrize(
    ("endpoint", "model", "where"),
    [("ftp://x/v1", "m", "runtime.endpoint"), ("https://x/v1", "", "runtime.model")],
)
def test_an_unusable_endpoint_or_no_model_is_refused_naming_where(
    endpoint: str, model: str, where: str
) -> None:
    with pytest.raises(RuntimeRefusedError) as raised:
        Runtime.checked(endpoint, model, None)
    assert raised.value.code == "openai.no-runtime"
    assert raised.value.details == {"where": where}


@pytest.mark.parametrize(
    "runtime",
    [
        ("http://models.example.com/v1", "m", KEY),
        ("ftp://x/v1", "m", None),
        ("https://x/v1", "m", KEY + "\r"),
    ],
)
def test_each_refusals_details_match_its_published_error_code(
    runtime: tuple[str, str, str | None],
) -> None:
    with pytest.raises(RuntimeRefusedError) as raised:
        Runtime.checked(*runtime)
    error = raised.value
    data = {
        "code": error.code,
        "problem": error.problem,
        "fix": error.fix,
        "details": error.details,
    }
    assert own_validator("errors.schema.json").is_valid(data)


def test_a_runtimes_repr_never_shows_its_credential() -> None:
    assert KEY not in repr(Runtime.checked("https://api.openai.com/v1", "m", KEY))


def _start(runtime: dict[str, Any] | None) -> RunStartParams:
    data: dict[str, Any] = {
        "runId": str(uuid.uuid4()),
        "direction": "d",
        "workspace": "/w",
        "options": {},
        "limits": {"eventMaxBytes": 65536},
        "effects": {"write": [], "delete": [], "move": []},
        "scratch": "/s",
    }
    if runtime is not None:
        data["runtime"] = runtime
    return RunStartParams.from_data(data)


OPENAI = {"name": "openai", "endpoint": "https://api.openai.com/v1", "model": "gpt-test"}


def test_run_starts_runtime_with_the_credential_from_troupe_runtime_credential() -> None:
    runtime = from_run_start(
        _start({**OPENAI, "credential": True}), {"TROUPE_RUNTIME_CREDENTIAL": KEY}
    )
    assert (runtime.endpoint.url, runtime.model, runtime.credential) == (
        "https://api.openai.com/v1",
        "gpt-test",
        KEY,
    )


def test_a_runtime_without_a_credential_has_none() -> None:
    runtime = from_run_start(_start({**OPENAI, "credential": False}), {})
    assert runtime.credential is None


def test_a_key_under_any_other_name_isnt_read() -> None:
    runtime = from_run_start(_start({**OPENAI, "credential": False}), {"OPENAI_API_KEY": KEY})
    assert runtime.credential is None


def test_a_run_start_without_a_runtime_is_refused_saying_to_name_one() -> None:
    with pytest.raises(RuntimeRefusedError) as raised:
        from_run_start(_start(None), {})
    assert raised.value.code == "openai.no-runtime"
    assert "runtime" in raised.value.fix


@pytest.mark.parametrize(
    ("credential", "environ"),
    [
        (True, {}),
        (True, {"TROUPE_RUNTIME_CREDENTIAL": ""}),
        (False, {"TROUPE_RUNTIME_CREDENTIAL": KEY}),
    ],
)
def test_a_run_start_and_an_environment_that_disagree_are_refused_without_the_value(
    credential: bool, environ: dict[str, str]
) -> None:
    with pytest.raises(RuntimeRefusedError) as raised:
        from_run_start(_start({**OPENAI, "credential": credential}), environ)
    error = raised.value
    assert error.code == "openai.credential-mismatch"
    assert KEY not in f"{error.problem} {error.fix} {error.details}"
    data = {
        "code": error.code,
        "problem": error.problem,
        "fix": error.fix,
        "details": error.details,
    }
    assert own_validator("errors.schema.json").is_valid(data)


@pytest.mark.parametrize("ending", ["\n", "\r", "\r\n", " ", "\t", "\x00"], ids=repr)
def test_a_key_with_a_line_ending_or_control_character_is_refused_without_its_value(
    ending: str,
) -> None:
    with pytest.raises(RuntimeRefusedError) as raised:
        Runtime.checked("https://api.openai.com/v1", "m", KEY + ending)
    error = raised.value
    assert error.code == "openai.malformed-credential"
    assert error.details == {"where": "TROUPE_RUNTIME_CREDENTIAL"}
    for text in (error.problem, error.fix):
        assert KEY not in text
        assert KEY[:8] not in text
