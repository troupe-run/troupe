"""Config's runtime fit agrees with each runner's own check: what config accepts for a runner, the
runner accepts, and what config refuses, the runner refuses (spec: runtimes, "An actor's runtime
fits its runner"; runtime-checks design D9).

The runner's check is the oracle. A runtime is generated from the shapes that decide fit (a path or
none, a lone /, a port, an IPv6 host, a credential or none), and only those: a host the runner
refuses for another reason, or plain HTTP with a credential to another machine, is left out, since
config refuses neither for fit.
"""

from hypothesis import given
from hypothesis import strategies as st

from troupe.core import defaults, interim, runtimes
from troupe_plugin_sdk.runner import RunStartParams, RunStartRuntime
from troupe_runner_anthropic import runtime as anthropic_runtime
from troupe_runner_lm_studio import runtime as lm_studio_runtime
from troupe_runner_ollama import runtime as ollama_runtime
from troupe_runner_openai import runtime as openai_runtime

KEY = "sk-test-q7ZxW9pL4vR2"

HOSTS = st.sampled_from(["127.0.0.1", "localhost", "[::1]", "models.example.com", "gpu-box"])
PORTS = st.sampled_from(["", ":1", ":11434", ":65535"])
PATHS = st.sampled_from(["", "/", "//", "///", "/v1", "/v1/", "/api/v1", "/openai/deployments/x"])


@st.composite
def runtimes_(draw: st.DrawFn) -> tuple[str, bool]:
    host, port, path = draw(HOSTS), draw(PORTS), draw(PATHS)
    credential = draw(st.booleans())
    loopback = host in ("127.0.0.1", "localhost", "[::1]")
    scheme = draw(st.sampled_from(["http", "https"])) if loopback or not credential else "https"
    return f"{scheme}://{host}{port}{path}", credential


def _ollama_accepts(endpoint: str, credential: bool) -> bool:
    try:
        ollama_runtime.checked(
            RunStartRuntime(name="box", endpoint=endpoint, model="m", credential=credential)
        )
    except ollama_runtime.RuntimeRefusedError:
        return False
    return True


def _openai_accepts(endpoint: str, credential: bool) -> bool:
    try:
        openai_runtime.Runtime.checked(endpoint, "m", KEY if credential else None)
    except openai_runtime.RuntimeRefusedError:
        return False
    return True


def _anthropic_accepts(endpoint: str, credential: bool) -> bool:
    try:
        anthropic_runtime.Runtime.checked(endpoint, "m", KEY if credential else None)
    except anthropic_runtime.RuntimeRefusedError:
        return False
    return True


def _lm_studio_accepts(endpoint: str, credential: bool) -> bool:
    start = RunStartParams.from_data(
        {
            "runId": "11111111-1111-4111-8111-111111111111",
            "direction": "d",
            "workspace": "w",
            "options": {},
            "limits": {"eventMaxBytes": 65536},
            "effects": {"write": [], "delete": [], "move": []},
            "scratch": "s",
            "onContextFull": "fail",
            "runtime": {
                "name": "box",
                "endpoint": endpoint,
                "model": "m",
                "credential": credential,
            },
        }
    )
    environ = {"TROUPE_RUNTIME_CREDENTIAL": KEY} if credential else {}
    try:
        lm_studio_runtime.from_run_start(start, environ)
    except lm_studio_runtime.RuntimeRefusedError:
        return False
    return True


ORACLES = {
    "anthropic": _anthropic_accepts,
    "lm-studio": _lm_studio_accepts,
    "ollama": _ollama_accepts,
    "openai": _openai_accepts,
}


def _config_accepts(runner: str, endpoint: str, credential: bool) -> bool:
    return not runtimes.unfit(interim.RUNNERS[runner].fit, endpoint, credential)


def test_every_runner_that_needs_a_runtime_has_an_oracle_here() -> None:
    assert {name for name, r in interim.RUNNERS.items() if r.runtime == "required"} == set(ORACLES)


@given(runtimes_(), st.sampled_from(sorted(ORACLES)))
def test_config_and_the_runner_agree_on_every_runtime(
    runtime: tuple[str, bool], runner: str
) -> None:
    endpoint, credential = runtime
    assert _config_accepts(runner, endpoint, credential) == ORACLES[runner](endpoint, credential)


def test_config_and_the_runner_agree_on_every_built_in_runtime() -> None:
    for runner, accepts in ORACLES.items():
        for name, built_in in defaults.RUNTIMES.items():
            endpoint = str(built_in["endpoint"])
            credential = "credential" in built_in
            assert _config_accepts(runner, endpoint, credential) == accepts(endpoint, credential), (
                runner,
                name,
            )
