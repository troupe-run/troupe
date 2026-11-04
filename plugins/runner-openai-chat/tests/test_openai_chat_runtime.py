"""The runtime value the runner talks to (spec: openai-chat-runner, "A credential never travels in
the clear"; design D2, D11). Reading it from run/start waits for #278's shape (task 1.1)."""

import pytest

from chat_harness import own_validator
from troupe_runner_openai_chat.runtime import Runtime, RuntimeRefusedError

KEY = "sk-canary-0123456789"


def test_plain_http_to_another_host_with_a_credential_is_refused_naming_the_endpoint() -> None:
    with pytest.raises(RuntimeRefusedError) as raised:
        Runtime.checked("http://models.example.com/v1", "m", KEY)
    assert raised.value.code == "openai-chat.insecure-endpoint"
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
    assert raised.value.code == "openai-chat.no-runtime"
    assert raised.value.details == {"where": where}


@pytest.mark.parametrize(
    "runtime",
    [("http://models.example.com/v1", "m", KEY), ("ftp://x/v1", "m", None)],
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
