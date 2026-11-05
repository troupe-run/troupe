"""How the runner reaches a service (spec: openai-runner, "The credential goes only in the
Authorization header", "A credential never travels in the clear", "Redirects are never followed";
design D3)."""

import contextlib
import json
import threading
import time

import pytest

from fake_endpoint import Cut, FakeEndpoint, Hold, Pause, Reply, error_reply, sse, text_reply
from troupe_runner_openai.service import (
    AbortedError,
    Call,
    EndpointError,
    NetworkError,
    StatusError,
    is_loopback,
    parse_endpoint,
)

KEY = "sk-canary-0123456789"


def _call(endpoint: str, credential: str | None = None, **timeouts: float) -> Call:
    return Call(parse_endpoint(endpoint), b'{"model": "m"}', credential, **timeouts)


# Endpoints


@pytest.mark.parametrize(
    "host", ["127.0.0.1", "127.0.0.2", "localhost", "LOCALHOST", "::1", "[::1]"]
)
def test_this_machine_counts_as_loopback(host: str) -> None:
    assert is_loopback(host)


@pytest.mark.parametrize(
    "host", ["127.0.0.1.example.com", "localhost.example.com", "10.0.0.1", "api.openai.com", ""]
)
def test_another_host_doesnt(host: str) -> None:
    assert not is_loopback(host)


def test_a_credential_over_plain_http_to_another_host_is_insecure() -> None:
    assert parse_endpoint("http://models.example.com/v1").is_insecure_for(has_credential=True)


@pytest.mark.parametrize(
    ("endpoint", "credential"),
    [
        ("http://127.0.0.1:11434/v1", True),
        ("http://localhost:1234/v1", True),
        ("https://models.example.com/v1", True),
        ("http://models.example.com/v1", False),
    ],
)
def test_https_this_machine_or_no_credential_isnt(endpoint: str, credential: bool) -> None:
    assert not parse_endpoint(endpoint).is_insecure_for(has_credential=credential)


@pytest.mark.parametrize(
    "endpoint",
    [
        "ftp://example.com/v1",
        "api.openai.com/v1",
        "https:///v1",
        "https://example.com/v1?x=1",
        "https://user:pw@example.com/v1",
        "https://example.com:99999/v1",
    ],
)
def test_an_endpoint_that_isnt_a_base_http_url_is_refused(endpoint: str) -> None:
    with pytest.raises(EndpointError):
        parse_endpoint(endpoint)


def test_requests_go_below_the_endpoint() -> None:
    assert parse_endpoint("https://api.openai.com/v1/").chat_url == (
        "https://api.openai.com/v1/chat/completions"
    )


# The credential


def test_the_credential_is_sent_only_as_a_bearer_authorization_header() -> None:
    with FakeEndpoint([text_reply("hi")]) as fake:
        list(_call(fake.endpoint, KEY).open().lines())
        (request,) = fake.requests
    assert request.headers["authorization"] == f"Bearer {KEY}"
    assert KEY not in request.body.decode()
    assert KEY not in request.path


def test_without_a_credential_there_is_no_authorization_header() -> None:
    with FakeEndpoint([text_reply("hi")]) as fake:
        list(_call(fake.endpoint).open().lines())
        (request,) = fake.requests
    assert "authorization" not in request.headers


def test_the_request_is_a_json_post_asking_for_a_stream() -> None:
    with FakeEndpoint([text_reply("hi")]) as fake:
        list(_call(fake.endpoint).open().lines())
        (request,) = fake.requests
    assert request.method == "POST"
    assert request.path == "/v1/chat/completions"
    assert request.headers["content-type"] == "application/json"
    assert request.headers["accept"] == "text/event-stream"
    assert request.json() == {"model": "m"}


# Redirects


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
def test_a_redirect_is_never_followed(status: int) -> None:
    with FakeEndpoint([text_reply("elsewhere")]) as elsewhere:
        location = elsewhere.endpoint + "/chat/completions"
        with (
            FakeEndpoint([Reply(status, headers=[("Location", location)])]) as fake,
            pytest.raises(StatusError) as raised,
        ):
            _call(fake.endpoint, KEY).open()
        assert elsewhere.requests == []
    assert raised.value.status == status
    assert raised.value.headers["location"] == location


# Statuses and the network


def test_an_error_status_carries_its_headers_and_body() -> None:
    reply = error_reply(429, "slow down", headers=[("Retry-After", "2")])
    with FakeEndpoint([reply]) as fake, pytest.raises(StatusError) as raised:
        _call(fake.endpoint).open()
    assert raised.value.status == 429
    assert raised.value.headers["retry-after"] == "2"
    assert json.loads(raised.value.body)["error"]["message"] == "slow down"


def test_a_refused_connection_is_a_network_error_naming_the_endpoint() -> None:
    with FakeEndpoint() as fake:
        endpoint = fake.endpoint
    with pytest.raises(NetworkError) as raised:
        _call(endpoint).open()
    assert endpoint in str(raised.value)


def test_the_streams_lines_arrive_without_their_endings() -> None:
    with FakeEndpoint([Reply(lines=["data: {}", "", "data: [DONE]"])]) as fake:
        assert list(_call(fake.endpoint).open().lines()) == ["data: {}", "", "data: [DONE]"]


def test_a_stream_silent_past_the_stream_timeout_is_a_network_error() -> None:
    with FakeEndpoint([Reply(lines=sse([Pause(2)]))]) as fake:
        response = _call(fake.endpoint, stream_timeout=0.3).open()
        with pytest.raises(NetworkError, match=r"sent nothing for 0\.3 seconds"):
            list(response.lines())


def test_a_stream_cut_short_ends_or_breaks_without_the_rest() -> None:
    with FakeEndpoint([Reply(lines=["data: {}", "", Cut(), "data: [DONE]"])]) as fake:
        received: list[str] = []
        with contextlib.suppress(NetworkError):
            received.extend(_call(fake.endpoint).open().lines())
    assert "data: [DONE]" not in received


def test_aborting_from_another_thread_wakes_a_blocked_read_within_a_second() -> None:
    with FakeEndpoint([Reply(lines=["data: {}", "", Hold()])]) as fake:
        call = _call(fake.endpoint)
        response = call.open()
        lines = response.lines()
        assert next(lines) == "data: {}"
        threading.Timer(0.2, call.abort).start()
        started = time.monotonic()
        with pytest.raises(AbortedError):
            list(lines)
        assert time.monotonic() - started < 1.2
        assert fake.wait_for_client_to_close(5)


def test_a_call_aborted_before_it_opens_sends_nothing() -> None:
    with FakeEndpoint([text_reply("hi")]) as fake:
        call = _call(fake.endpoint)
        call.abort()
        with pytest.raises(AbortedError):
            call.open()
        assert fake.requests == []
