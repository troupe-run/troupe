"""The run's runtime, as the runner reads it (spec: ollama-runner, "The service comes from the run's
runtime", "The runtime's endpoint is one the runner can use", "A runtime with a credential is
refused"; ollama-uses-runtime design D2, D3, D4).

The endpoint cases are the ones the runner checked when the endpoint was an option, less those the
runner contract's own pattern now refuses first (user info, a query, a fragment, a scheme that isn't
http or https), which run/start's parsing covers.
"""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from troupe_plugin_sdk import runner as p
from troupe_runner_ollama.runtime import (
    Runtime,
    RuntimeRefusedError,
    checked,
    env_name,
    from_run_start,
)


def _runtime(endpoint: str, *, name: str = "ollama", credential: bool = False) -> p.RunStartRuntime:
    # from_data, as run/start's parsing reads it, so the contract's own pattern applies.
    return p.RunStartRuntime.from_data(
        {"name": name, "endpoint": endpoint, "model": "qwen3:4b", "credential": credential}
    )


def _refused(runtime: p.RunStartRuntime) -> RuntimeRefusedError:
    with pytest.raises(RuntimeRefusedError) as caught:
        checked(runtime)
    return caught.value


def _params(runtime: p.RunStartRuntime | None) -> p.RunStartParams:
    return p.RunStartParams(
        run_id="00000000-0000-4000-8000-000000000000",
        direction="d",
        workspace="/w",
        options={},
        limits=p.StartLimits(event_max_bytes=65536),
        effects=p.EffectsDeclaration(write=[], delete=[], move=[]),
        scratch="/s",
        on_context_full="fail",
        runtime=runtime,
    )


def test_the_runtimes_name_endpoint_and_model_are_what_the_run_uses() -> None:
    runtime = from_run_start(_params(_runtime("http://gpu-box.local:11434/")))
    assert runtime == Runtime("ollama", "http://gpu-box.local:11434", "qwen3:4b")


def test_a_run_start_without_a_runtime_is_refused_naming_where_to_set_one() -> None:
    with pytest.raises(RuntimeRefusedError) as caught:
        from_run_start(_params(None))
    assert caught.value.code == "ollama.no-runtime"
    assert caught.value.where == "runtime"
    assert "actors.<name>.runtime=ollama" in caught.value.fix


def test_a_runtime_with_a_credential_is_refused_naming_the_runtime() -> None:
    error = _refused(_runtime("http://127.0.0.1:11434", name="cloud", credential=True))
    assert error.code == "ollama.credential-unsupported"
    assert error.where == "runtime.credential"
    assert "'cloud'" in error.problem
    assert "actors.<name>.runtime=ollama" in error.fix


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://127.0.0.1:11434",
        "http://localhost:11434/",
        "http://[::1]:11434",
        "https://gpu-box.local",
        "http://gpu-box.local:11434",
        "http://127.0.0.1:65535",
        "http://" + "a" * 63 + ".example",
    ],
)
def test_a_host_and_an_optional_port_is_accepted_without_its_trailing_slash(endpoint: str) -> None:
    assert checked(_runtime(endpoint)).endpoint == endpoint.rstrip("/")


@pytest.mark.parametrize(
    ("endpoint", "problem"),
    [
        ("http://127.0.0.1:11434/api", "has a path"),
        ("http://127.0.0.1:11434/v1", "for the openai runner"),
        ("http://127.0.0.1:11434//", "has a path"),
        ("http://127.0.0.1:99999", "a port is at most 65535"),
        ("http://127.0.0.1:65536", "a port is at most 65535"),
        ("http://a..b:11434", "1 to 63"),
        ("http://" + "a" * 64 + ".com", "1 to 63"),
        ("http://host.:11434", "1 to 63"),
    ],
)
def test_an_endpoint_the_runner_cant_use_is_refused_naming_where_to_change_it(
    endpoint: str, problem: str
) -> None:
    error = _refused(_runtime(endpoint, name="lm-box"))
    assert error.code == "ollama.invalid-runtime"
    assert error.where == "runtime.endpoint"
    assert problem in error.problem
    assert "runtimes.lm-box.endpoint" in error.fix
    assert "TROUPE_RUNTIME_LM_BOX_ENDPOINT" in error.fix


@pytest.mark.parametrize(
    ("name", "variable"),
    [
        ("ollama", "TROUPE_RUNTIME_OLLAMA_ENDPOINT"),
        ("gpu-box", "TROUPE_RUNTIME_GPU_BOX_ENDPOINT"),
        ("a-b-c", "TROUPE_RUNTIME_A_B_C_ENDPOINT"),
    ],
)
def test_the_endpoint_variable_is_the_runtimes_name_in_capitals_with_underscores(
    name: str, variable: str
) -> None:
    assert env_name(name, "endpoint") == variable


_HOSTS = st.sampled_from(
    ["127.0.0.1", "localhost", "[::1]", "gpu-box.local", "a..b", "-", "x" * 64]
)
_PORTS = st.sampled_from(["", ":11434", ":1", ":65535", ":65536", ":99999", ":0"])
_TAILS = st.sampled_from(["", "/", "//", "/api", "/v1", "/a/b"])


@given(st.sampled_from(["http://", "https://"]), _HOSTS, _PORTS, _TAILS)
def test_any_endpoint_the_contract_accepts_is_used_or_refused_never_an_other_error(
    scheme: str, host: str, port: str, tail: str
) -> None:
    endpoint = f"{scheme}{host}{port}{tail}"
    try:
        runtime = _runtime(endpoint)
    except p.ProtocolError:
        return  # the contract's own pattern refused it, before the runner reads it
    refused: RuntimeRefusedError | None = None
    try:
        used = checked(runtime).endpoint
    except RuntimeRefusedError as error:
        refused = error
    if refused is not None:
        assert refused.code == "ollama.invalid-runtime"
        return
    assert not used.endswith("/")
    assert tail in ("", "/")
