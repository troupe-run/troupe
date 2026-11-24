"""How the runner reaches a service through the openai package, against the fake endpoint: the
credential only in a bearer Authorization header, no redirect followed, no retry by the library,
no proxy for this machine, only the headers a request needs, and how errors, silences and cut
streams come back (spec: openai-runner, "The credential goes only in the Authorization header",
"A credential never travels in the clear", "Redirects are never followed", "Every timeout the
library applies is one of the runner's named settings"; openai-library design D2-D4a).

Its tests that stay in their own process are in unit/test_openai_service.py."""

import contextlib
import json
from typing import Any

import pytest

from fake_endpoint import Cut, FakeEndpoint, Hold, Pause, Reply, error_reply, sse, text_reply
from openai_service_shared import KEY, PARAMS
from troupe_runner_openai.service import (
    SENT_HEADERS,
    USER_AGENT,
    NetworkError,
    NotAStreamError,
    Opened,
    Service,
    StatusError,
    parse_endpoint,
    proxy_for,
)


def _open(endpoint: str, credential: str | None = None, **settings: Any) -> Opened:  # noqa: ANN401
    """One request to ``endpoint`` through a Service of its own, with ``settings``."""
    return Service(parse_endpoint(endpoint), credential, **settings).stream(PARAMS)


def _drain(endpoint: str, credential: str | None = None, **settings: Any) -> list[Any]:  # noqa: ANN401
    return list(_open(endpoint, credential, **settings).events)


# The credential


def test_the_credential_is_sent_only_as_a_bearer_authorization_header() -> None:
    with FakeEndpoint([text_reply("hi")]) as fake:
        _drain(fake.endpoint, KEY)
        (request,) = fake.requests
    assert request.headers["authorization"] == f"Bearer {KEY}"
    assert KEY not in request.body.decode()
    assert KEY not in request.path


def test_without_a_credential_there_is_no_authorization_header() -> None:
    with FakeEndpoint([text_reply("hi")]) as fake:
        _drain(fake.endpoint)
        (request,) = fake.requests
    assert "authorization" not in request.headers
    assert "no-credential" not in json.dumps(request.headers)


def test_the_request_is_a_json_post_of_the_parameters() -> None:
    with FakeEndpoint([text_reply("hi")]) as fake:
        _drain(fake.endpoint)
        (request,) = fake.requests
    assert request.method == "POST"
    assert request.path == "/v1/responses"
    assert request.headers["content-type"] == "application/json"
    assert request.json() == PARAMS


def test_a_header_the_key_cant_go_in_is_reported_without_the_key() -> None:
    with FakeEndpoint([text_reply("ok")]) as fake, pytest.raises(NetworkError) as raised:
        _open(fake.endpoint, KEY + "\r")
    assert KEY not in str(raised.value)
    assert KEY[:8] not in str(raised.value)


# Redirects, retries and proxies


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
def test_a_redirect_is_never_followed(status: int) -> None:
    with FakeEndpoint([text_reply("elsewhere")]) as elsewhere:
        location = elsewhere.endpoint + "/responses"
        with (
            FakeEndpoint([Reply(status, headers=[("Location", location)])]) as fake,
            pytest.raises(StatusError) as raised,
        ):
            _open(fake.endpoint, KEY)
        assert elsewhere.requests == []
        assert len(fake.requests) == 1
    assert raised.value.status == status
    assert raised.value.headers["location"] == location


def test_the_library_never_retries_a_server_error_itself() -> None:
    with FakeEndpoint([error_reply(500, "boom"), text_reply("ok")]) as fake:
        with pytest.raises(StatusError):
            _open(fake.endpoint)
        assert len(fake.requests) == 1


def test_an_endpoint_on_this_machine_never_goes_through_a_proxy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with FakeEndpoint([text_reply("proxied")]) as proxy, FakeEndpoint([text_reply("ok")]) as fake:
        for name in ("HTTP_PROXY", "http_proxy"):
            monkeypatch.setenv(name, proxy.endpoint.removesuffix("/v1"))
        for name in ("NO_PROXY", "no_proxy"):
            monkeypatch.delenv(name, raising=False)
        assert proxy_for(parse_endpoint(fake.endpoint)) is None
        _drain(fake.endpoint)
        assert proxy.requests == []
        assert len(fake.requests) == 1


# Statuses, timeouts and the network


def test_an_error_status_carries_its_headers_and_body() -> None:
    reply = error_reply(429, "slow down", headers=[("Retry-After", "2")])
    with FakeEndpoint([reply]) as fake, pytest.raises(StatusError) as raised:
        _open(fake.endpoint)
    assert raised.value.status == 429
    assert raised.value.headers["retry-after"] == "2"
    assert json.loads(raised.value.body)["error"]["message"] == "slow down"


def test_a_refused_connection_is_a_network_error_naming_the_endpoint() -> None:
    with FakeEndpoint() as fake:
        endpoint = fake.endpoint
    with pytest.raises(NetworkError) as raised:
        _open(endpoint)
    assert endpoint in str(raised.value)


def test_a_stream_silent_past_the_stream_timeout_is_a_network_error() -> None:
    with FakeEndpoint([Reply(lines=sse([Pause(2)]))]) as fake:
        opened = _open(fake.endpoint, stream_timeout=0.3)
        with pytest.raises(NetworkError, match=r"sent nothing for 0\.3 seconds"):
            list(opened.events)


def test_a_connection_held_with_nothing_sent_is_abandoned_at_the_stream_timeout() -> None:
    with FakeEndpoint([Reply(lines=[Hold()])]) as fake:
        opened = _open(fake.endpoint, stream_timeout=0.3)
        with pytest.raises(NetworkError, match=r"sent nothing for 0\.3 seconds"):
            list(opened.events)


def test_a_stream_cut_short_ends_or_breaks_without_the_rest() -> None:
    final = '{"type": "response.completed", "response": {"status": "completed", "output": []}}'
    with FakeEndpoint(
        [Reply(lines=['data: {"type": "x"}', "", Cut(), f"data: {final}", ""])]
    ) as fake:
        received: list[Any] = []
        with contextlib.suppress(NetworkError):
            received.extend(_open(fake.endpoint).events)
    assert [e["type"] for e in received] == ["x"]


def test_a_200_with_a_json_body_is_not_a_stream_with_its_body() -> None:
    with (
        FakeEndpoint([Reply(200, body=b'{"id": "resp_1"}')]) as fake,
        pytest.raises(NotAStreamError) as raised,
    ):
        _open(fake.endpoint)
    assert raised.value.body == b'{"id": "resp_1"}'
    assert raised.value.broke is None


def test_a_body_that_breaks_off_before_its_length_says_so() -> None:
    short = Reply(
        200,
        headers=[("Content-Type", "application/json"), ("Content-Length", "100")],
        chunks=[b'{"id": "re'],
    )
    with FakeEndpoint([short]) as fake, pytest.raises(NotAStreamError) as raised:
        _open(fake.endpoint)
    assert raised.value.broke is not None


def test_the_runner_asks_for_no_compression() -> None:
    with FakeEndpoint([text_reply("hi")]) as fake:
        _drain(fake.endpoint)
        (request,) = fake.requests
    assert request.headers["accept-encoding"] == "identity"


def test_each_request_carries_only_the_headers_it_needs_and_none_of_the_librarys_telemetry() -> (
    None
):
    """Owner, 2026-11-18: no X-Stainless-* header (OS, CPU, Python and package versions) or any
    other the library adds leaves the runner."""
    with FakeEndpoint([text_reply("hi")]) as fake:
        _drain(fake.endpoint, KEY)
        (request,) = fake.requests
    assert set(request.headers) <= SENT_HEADERS
    assert not any(name.startswith("x-") for name in request.headers)
    assert request.headers["user-agent"] == USER_AGENT
    assert request.headers["authorization"] == f"Bearer {KEY}"
    assert request.headers["content-type"] == "application/json"


def test_without_a_credential_the_headers_are_the_same_but_authorization() -> None:
    with FakeEndpoint([text_reply("hi")]) as fake:
        _drain(fake.endpoint)
        (request,) = fake.requests
    assert set(request.headers) <= SENT_HEADERS - {"authorization"}
