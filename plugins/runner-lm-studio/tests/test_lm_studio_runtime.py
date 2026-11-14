"""The runtime: the library's host and port from its endpoint, and what's refused (spec:
lm-studio-runner, "The service comes from the run's runtime", "The runtime's endpoint is the
library's host and port", "An endpoint the library can't use is refused", "A runtime with a
credential is refused")."""

from typing import Any

import pytest

from troupe_plugin_sdk.runner import Price, RunStartParams
from troupe_runner_lm_studio.runtime import RuntimeRefusedError, api_host, from_run_start

CANARY = "lm-canary-0123456789"


def _start(
    endpoint: str = "http://127.0.0.1:1234",
    model: str = "small-model",
    credential: bool = False,
    runtime: bool = True,
    price: dict[str, float] | None = None,
) -> RunStartParams:
    data: dict[str, Any] = {
        "runId": "11111111-1111-4111-8111-111111111111",
        "direction": "Do it.",
        "workspace": "ws",
        "options": {},
        "limits": {"eventMaxBytes": 65536},
        "effects": {"write": [], "delete": [], "move": []},
        "scratch": "scratch",
        "onContextFull": "fail",
    }
    if runtime:
        data["runtime"] = {
            "name": "lm-studio",
            "endpoint": endpoint,
            "model": model,
            "credential": credential,
        }
        if price is not None:
            data["runtime"]["price"] = price
    return RunStartParams.from_data(data)


@pytest.mark.parametrize(
    ("endpoint", "host"),
    [
        ("http://127.0.0.1:1234", "127.0.0.1:1234"),
        ("http://127.0.0.1:1234/", "127.0.0.1:1234"),
        ("http://localhost:1234", "localhost:1234"),
        ("http://[::1]:1234", "[::1]:1234"),
        ("http://gpu-box.local:1234", "gpu-box.local:1234"),
        ("http://lm.example.com", "lm.example.com:80"),
    ],
)
def test_the_endpoint_is_the_librarys_host_and_port_always_with_a_port(
    endpoint: str, host: str
) -> None:
    assert api_host(endpoint) == host


def test_the_openai_compatible_base_is_refused_naming_the_server_root() -> None:
    with pytest.raises(RuntimeRefusedError) as caught:
        api_host("http://127.0.0.1:1234/v1")
    assert caught.value.code == "lm-studio.unsupported-endpoint"
    assert "http://127.0.0.1:1234." in caught.value.fix
    assert caught.value.details == {"endpoint": "http://127.0.0.1:1234/v1"}


def test_https_is_refused_saying_the_library_speaks_only_plain_ws() -> None:
    with pytest.raises(RuntimeRefusedError) as caught:
        api_host("https://lm.example.com")
    assert caught.value.code == "lm-studio.unsupported-endpoint"
    assert "ws://" in caught.value.problem


@pytest.mark.parametrize(
    "endpoint",
    [
        "ftp://host:1",
        "http://",
        "http://user:pw@host:1234",
        "http://host:1234/?q=1",
        "http://host:99999",
    ],
)
def test_an_endpoint_the_library_cant_use_is_refused(endpoint: str) -> None:
    with pytest.raises(RuntimeRefusedError) as caught:
        api_host(endpoint)
    assert caught.value.code == "lm-studio.unsupported-endpoint"
    assert "pw" not in caught.value.problem + caught.value.fix + str(caught.value.details)


def test_a_run_without_a_runtime_is_refused_saying_to_name_one() -> None:
    with pytest.raises(RuntimeRefusedError) as caught:
        from_run_start(_start(runtime=False), {})
    assert caught.value.code == "lm-studio.no-runtime"
    assert "runtime=lm-studio" in caught.value.fix


def test_the_runtimes_model_and_price_are_the_runs() -> None:
    runtime = from_run_start(_start(model="small-model", price={"input": 2, "output": 8}), {})
    assert (runtime.model, runtime.api_host, runtime.price) == (
        "small-model",
        "127.0.0.1:1234",
        Price(input=2, output=8),
    )


def test_a_runtime_with_a_credential_is_refused_without_the_token() -> None:
    with pytest.raises(RuntimeRefusedError) as caught:
        from_run_start(_start(credential=True), {"TROUPE_RUNTIME_CREDENTIAL": CANARY})
    assert caught.value.code == "lm-studio.credential-unsupported"
    assert "Require Authentication" in caught.value.fix
    assert CANARY not in caught.value.problem + caught.value.fix + str(caught.value.details)


def test_a_credential_run_start_doesnt_mention_is_a_mismatch_without_the_value() -> None:
    with pytest.raises(RuntimeRefusedError) as caught:
        from_run_start(_start(), {"TROUPE_RUNTIME_CREDENTIAL": CANARY})
    assert caught.value.code == "lm-studio.credential-mismatch"
    assert CANARY not in caught.value.problem + caught.value.fix + str(caught.value.details)


def test_an_in_process_runtime_without_an_endpoint_is_refused_naming_the_endpoint() -> None:
    # In-process-runner design D5: config wouldn't pair one with an LM Studio actor; the runner
    # still refuses it rather than failing on a missing endpoint.
    data = _start().to_data()
    del data["runtime"]["endpoint"]
    with pytest.raises(RuntimeRefusedError) as raised:
        from_run_start(RunStartParams.from_data(data), {})
    assert raised.value.code == "lm-studio.no-runtime"
    assert raised.value.details == {"where": "runtime.endpoint"}
