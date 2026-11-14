"""The runtime the runner talks to, read from run/start (spec: anthropic-runner, "The service comes
from the run's runtime", "The runtime's endpoint is the API's base URL", "The credential is read
from TROUPE_RUNTIME_CREDENTIAL", "A credential never travels in the clear"; design D3, D4).

Only what runtime.py decides is checked here: the Runtime the runner builds, and each refusal's
code, details and words. That no request is sent after a refusal is the runner's, checked where it
drives the process."""

import uuid
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from anthropic_harness import CANARY, own_validator
from troupe_plugin_sdk.runner import RunStartParams
from troupe_runner_anthropic.runtime import (
    Runtime,
    RuntimeRefusedError,
    from_run_start,
    is_loopback,
    parse_endpoint,
)

KEY = CANARY


def _published(error: RuntimeRefusedError) -> bool:
    data = {
        "code": error.code,
        "problem": error.problem,
        "fix": error.fix,
        "details": error.details,
    }
    return own_validator("errors.schema.json").is_valid(data)


def _refused(endpoint: str, model: str = "m", credential: str | None = None) -> RuntimeRefusedError:
    with pytest.raises(RuntimeRefusedError) as raised:
        Runtime.checked(endpoint, model, credential)
    return raised.value


# Requirement: The runtime's endpoint is the API's base URL


@pytest.mark.parametrize(
    ("endpoint", "messages"),
    [
        ("http://127.0.0.1:1234", "http://127.0.0.1:1234/v1/messages"),
        ("https://api.anthropic.com", "https://api.anthropic.com/v1/messages"),
        ("https://api.anthropic.com/", "https://api.anthropic.com/v1/messages"),
        ("https://gateway.example/anthropic", "https://gateway.example/anthropic/v1/messages"),
        ("http://[::1]:8000", "http://[::1]:8000/v1/messages"),
    ],
)
def test_requests_go_to_v1_messages_below_the_endpoint(endpoint: str, messages: str) -> None:
    """Scenarios "Where a request goes" and "A gateway's own path", as far as the URL the runner
    gives the library; the request reaching it is the runner tests'."""
    assert parse_endpoint(endpoint).messages_url == messages


@pytest.mark.parametrize(
    ("endpoint", "root"),
    [
        ("http://127.0.0.1:1234/v1", "http://127.0.0.1:1234"),
        ("http://127.0.0.1:1234/v1/", "http://127.0.0.1:1234"),
        ("https://gateway.example/anthropic/v1", "https://gateway.example/anthropic"),
    ],
)
def test_an_endpoint_ending_in_v1_is_refused_naming_the_base_without_it(
    endpoint: str, root: str
) -> None:
    """Scenario "An OpenAI-style base"."""
    error = _refused(endpoint)
    assert error.code == "anthropic.unsupported-endpoint"
    assert error.details == {"where": "runtime.endpoint"}
    assert "/v1/messages" in error.problem
    assert error.fix.endswith(f": {root}.")
    assert _published(error)


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://api.anthropic.com?beta=1",
        "https://api.anthropic.com/?beta=1",
        "https://api.anthropic.com#top",
        "https://api.anthropic.com/anthropic?",
        "https://api.anthropic.com#",
    ],
)
def test_an_endpoint_with_a_query_or_fragment_is_refused_saying_so(endpoint: str) -> None:
    error = _refused(endpoint)
    assert error.code == "anthropic.unsupported-endpoint"
    assert error.details == {"where": "runtime.endpoint"}
    assert "query or fragment" in error.problem
    assert _published(error)


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://user:hunter2-secret@api.anthropic.com",
        "https://hunter2-secret@api.anthropic.com",
        "https://user:hunter2-secret@api.anthropic.com/v1",
        "https://user:hunter2-secret@api.anthropic.com?q=1",
        "ftp://user:hunter2-secret@api.anthropic.com",
        "https://user:hunter2-secret@api.anthropic.com:notaport",
    ],
)
def test_an_endpoint_holding_user_info_is_refused_without_repeating_it(endpoint: str) -> None:
    error = _refused(endpoint)
    assert error.code == "anthropic.unsupported-endpoint"
    assert error.details == {"where": "runtime.endpoint"}
    for text in (error.problem, error.fix, str(error)):
        assert "hunter2" not in text


@given(
    secret=st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789-_.~", min_size=1).map(
        lambda tail: "pw~~" + tail
    )
)
def test_no_refusal_repeats_the_password_of_an_endpoint_with_user_info(secret: str) -> None:
    for endpoint in (
        f"https://u:{secret}@example.com",
        f"https://u:{secret}@example.com/v1",
        f"https://u:{secret}@example.com/?x",
        f"https://u:{secret}@example.com:99999",
    ):
        with pytest.raises(RuntimeRefusedError) as raised:
            parse_endpoint(endpoint)
        error = raised.value
        assert secret not in f"{error.problem} {error.fix} {error.details}"


@pytest.mark.parametrize(
    "endpoint",
    ["ftp://example.com", "example.com", "https://", "file:///tmp/x", "http://example.com:99999"],
)
def test_an_endpoint_that_isnt_an_http_url_with_a_host_is_refused(endpoint: str) -> None:
    error = _refused(endpoint)
    assert error.code == "anthropic.unsupported-endpoint"
    assert error.details == {"where": "runtime.endpoint"}
    assert "https://api.anthropic.com" in error.fix
    assert _published(error)


def test_an_endpoint_is_kept_without_its_trailing_slash() -> None:
    endpoint = parse_endpoint("https://gateway.example/anthropic/")
    assert (endpoint.url, endpoint.scheme, endpoint.host) == (
        "https://gateway.example/anthropic",
        "https",
        "gateway.example",
    )


# Requirement: The service comes from the run's runtime


def test_a_runtime_with_no_model_is_refused_naming_the_model() -> None:
    error = _refused("https://api.anthropic.com", model="")
    assert error.code == "anthropic.no-runtime"
    assert error.details == {"where": "runtime.model"}
    assert _published(error)


def test_a_runtimes_repr_never_shows_its_credential() -> None:
    assert KEY not in repr(Runtime.checked("https://api.anthropic.com", "m", KEY))


# Requirement: A credential never travels in the clear


def test_plain_http_to_another_host_with_a_credential_is_refused_naming_the_endpoint() -> None:
    """Scenario "Plain HTTP to another host"."""
    error = _refused("http://models.example.com", credential=KEY)
    assert error.code == "anthropic.insecure-endpoint"
    assert error.details == {"endpoint": "http://models.example.com"}
    assert "https" in error.fix
    assert KEY not in f"{error.problem} {error.fix}"
    assert _published(error)


@pytest.mark.parametrize(
    ("endpoint", "credential"),
    [
        ("http://127.0.0.1:1234", KEY),
        ("http://localhost:1234", KEY),
        ("http://LOCALHOST:1234", KEY),
        ("http://[::1]:1234", KEY),
        ("http://127.8.9.10:1234", KEY),
        ("https://api.anthropic.com", KEY),
        ("http://models.example.com", None),
        ("http://models.example.com", ""),
    ],
)
def test_https_this_machine_or_no_credential_is_a_runtime(
    endpoint: str, credential: str | None
) -> None:
    """Scenario "Plain HTTP to this machine", and the cases the refusal doesn't cover."""
    runtime = Runtime.checked(endpoint, "m", credential)
    assert runtime.endpoint.url == endpoint
    assert runtime.credential == (credential or None)


@pytest.mark.parametrize(
    ("host", "loopback"),
    [
        ("localhost", True),
        ("127.0.0.1", True),
        ("[::1]", True),
        ("::1", True),
        ("127.0.0.1.example.com", False),
        ("localhost.example.com", False),
        ("10.0.0.1", False),
        ("example.com", False),
    ],
)
def test_only_localhost_and_loopback_addresses_are_this_machine(host: str, loopback: bool) -> None:
    assert is_loopback(host) is loopback


def test_a_loopback_lookalike_host_with_a_credential_over_http_is_refused() -> None:
    error = _refused("http://127.0.0.1.example.com", credential=KEY)
    assert error.code == "anthropic.insecure-endpoint"


# Requirement: The credential is read from TROUPE_RUNTIME_CREDENTIAL


def _start(runtime: dict[str, Any] | None) -> RunStartParams:
    data: dict[str, Any] = {
        "runId": str(uuid.uuid4()),
        "direction": "d",
        "workspace": "/w",
        "options": {},
        "limits": {"eventMaxBytes": 65536},
        "effects": {"write": [], "delete": [], "move": []},
        "scratch": "/s",
        "onContextFull": "fail",
    }
    if runtime is not None:
        data["runtime"] = runtime
    return RunStartParams.from_data(data)


ANTHROPIC = {"name": "anthropic", "endpoint": "https://api.anthropic.com", "model": "claude-test"}
LM_STUDIO = {
    "name": "lm-studio-messages",
    "endpoint": "http://127.0.0.1:1234",
    "model": "google/gemma-4-e4b",
}


def test_run_starts_runtime_with_the_credential_from_troupe_runtime_credential() -> None:
    runtime = from_run_start(
        _start({**ANTHROPIC, "credential": True}), {"TROUPE_RUNTIME_CREDENTIAL": KEY}
    )
    assert (runtime.endpoint.url, runtime.model, runtime.credential) == (
        "https://api.anthropic.com",
        "claude-test",
        KEY,
    )


def test_a_local_engines_runtime_without_a_credential_is_its_endpoint_and_model() -> None:
    """Scenario "A local engine through a runtime of your own", as far as the runtime goes."""
    runtime = from_run_start(_start({**LM_STUDIO, "credential": False}), {})
    assert (runtime.endpoint.messages_url, runtime.model, runtime.credential) == (
        "http://127.0.0.1:1234/v1/messages",
        "google/gemma-4-e4b",
        None,
    )


def test_run_starts_price_is_the_runtimes_price() -> None:
    price = {"input": 1, "output": 5, "cacheRead": 0.1}
    runtime = from_run_start(_start({**ANTHROPIC, "credential": False, "price": price}), {})
    assert runtime.price is not None
    assert runtime.price.to_data() == price


def test_a_run_start_without_a_price_gives_a_runtime_without_one() -> None:
    assert from_run_start(_start({**ANTHROPIC, "credential": False}), {}).price is None


@pytest.mark.parametrize(
    "variable", ["ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "OPENAI_API_KEY"]
)
def test_a_key_under_any_other_name_isnt_read(variable: str) -> None:
    runtime = from_run_start(_start({**ANTHROPIC, "credential": False}), {variable: KEY})
    assert runtime.credential is None


def test_a_run_start_without_a_runtime_is_refused_saying_to_name_one() -> None:
    """Scenario "A run without a runtime"."""
    with pytest.raises(RuntimeRefusedError) as raised:
        from_run_start(_start(None), {})
    error = raised.value
    assert error.code == "anthropic.no-runtime"
    assert "Name a runtime for the actor" in error.fix
    assert _published(error)


@pytest.mark.parametrize(
    ("credential", "environ"),
    [
        (True, {}),
        (True, {"TROUPE_RUNTIME_CREDENTIAL": ""}),
        (False, {"TROUPE_RUNTIME_CREDENTIAL": KEY}),
    ],
    ids=["promised and unset", "promised and empty", "unmentioned and set"],
)
def test_a_run_start_and_an_environment_that_disagree_are_refused_without_the_value(
    credential: bool, environ: dict[str, str]
) -> None:
    """Scenarios "A credential run start promises and the environment lacks" and "A credential run
    start doesn't mention"."""
    with pytest.raises(RuntimeRefusedError) as raised:
        from_run_start(_start({**ANTHROPIC, "credential": credential}), environ)
    error = raised.value
    assert error.code == "anthropic.credential-mismatch"
    assert error.details == {"where": "TROUPE_RUNTIME_CREDENTIAL"}
    text = f"{error.problem} {error.fix} {error.details} {error}"
    for part in (KEY, KEY[:8], KEY[-8:]):
        assert part not in text
    assert _published(error)


@pytest.mark.parametrize(
    "ending", ["\n", "\r", "\r\n", " ", "\t", "\x00", "\x7f", "€", "é"], ids=repr
)
def test_a_key_holding_a_character_a_header_cant_carry_is_refused_without_its_value(
    ending: str,
) -> None:
    """Scenario "A key read with its line ending", and the other characters it covers."""
    error = _refused("https://api.anthropic.com", credential=KEY + ending)
    assert error.code == "anthropic.malformed-credential"
    assert error.details == {"where": "TROUPE_RUNTIME_CREDENTIAL"}
    for text in (error.problem, error.fix, str(error)):
        assert KEY not in text
        assert KEY[:8] not in text
        assert KEY[-8:] not in text
    assert _published(error)


def test_a_malformed_key_in_the_environment_is_refused_as_malformed_by_from_run_start() -> None:
    with pytest.raises(RuntimeRefusedError) as raised:
        from_run_start(
            _start({**ANTHROPIC, "credential": True}), {"TROUPE_RUNTIME_CREDENTIAL": KEY + "\r\n"}
        )
    assert raised.value.code == "anthropic.malformed-credential"
