"""The one module that uses the anthropic package, against the fake Messages API (spec:
anthropic-runner, "The library finds nothing of its own", "The credential goes only in the
Authorization header", "Redirects are never followed", "Every timeout the library applies is one of
the runner's named settings", "The library's own logging stays out of the run's output"; design D4,
D10).

Where it's cheap, each guarantee is also shown failing for the library's own default client, so a
test here fails if the runner's setting is lost rather than passing because the library happened to
behave."""

import io
import json
import logging
import os
import socket
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import anthropic
import httpx2
import pytest

from fake_messages import (
    FakeEndpoint,
    Hold,
    Reply,
    error_reply,
    sse,
    start,
    stream_error_reply,
    text_reply,
)
from troupe_runner_anthropic.defaults import (
    CONNECT_TIMEOUT_SECONDS,
    LIBRARY_LOG_MAX_BYTES,
    STREAM_TIMEOUT_SECONDS,
    WRITE_TIMEOUT_SECONDS,
)
from troupe_runner_anthropic.masking import MASK, Mask
from troupe_runner_anthropic.runtime import Runtime
from troupe_runner_anthropic.service import (
    LIBRARY_LOGGERS,
    NetworkError,
    NotAStreamError,
    Service,
    StatusError,
    UnreadableError,
    quiet_library_logging,
)

KEY = "sk-ant-canary-0123456789"
PARAMS: dict[str, Any] = {
    "model": "m",
    "max_tokens": 5,
    "messages": [{"role": "user", "content": "hi"}],
}
LIBRARY_VARIABLES = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_CUSTOM_HEADERS",
    "ANTHROPIC_PROFILE",
    "ANTHROPIC_CONFIG_DIR",
    "ANTHROPIC_LOG",
)
ENV_KEY = "sk-ant-env-key-canary"
ENV_TOKEN = "env-auth-token-canary"  # noqa: S105 - a canary, not a secret
PROFILE_TOKEN = "profile-token-canary"  # noqa: S105 - a canary, not a secret
CUSTOM_HEADERS = "X-Leak: from-the-environment\nX-Other: also"


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """No ANTHROPIC_* variable of the machine's own reaches a test; each test sets its own, and
    monkeypatch restores them, whatever the runner removed."""
    for name in [n for n in os.environ if n.upper().startswith("ANTHROPIC_")]:
        monkeypatch.delenv(name)


def _service(endpoint: str, credential: str | None = None, **timeouts: float) -> Service:
    return Service(Runtime.checked(endpoint, "m", credential), **timeouts)


def _events(service: Service, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    try:
        return list(service.stream(PARAMS if params is None else params).events)
    finally:
        service.close()


def _default_client(**kwargs: Any) -> anthropic.Anthropic:  # noqa: ANN401
    """The library's own client, as it builds itself."""
    return anthropic.Anthropic(max_retries=0, **kwargs)


def _default_events(client: anthropic.Anthropic) -> list[str]:
    stream = client.messages.create(**PARAMS, stream=True)
    return [event.type for event in stream]


def _credential_headers(headers: dict[str, str]) -> dict[str, str]:
    return {k: v for k, v in headers.items() if k in ("authorization", "x-api-key")}


# Requirement: The library finds nothing of its own


def test_the_librarys_variables_send_no_credential_or_custom_header_and_dont_move_the_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with FakeEndpoint([text_reply("elsewhere")]) as elsewhere:
        monkeypatch.setenv("ANTHROPIC_API_KEY", ENV_KEY)
        monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", ENV_TOKEN)
        monkeypatch.setenv("ANTHROPIC_BASE_URL", elsewhere.endpoint)
        monkeypatch.setenv("ANTHROPIC_CUSTOM_HEADERS", CUSTOM_HEADERS)
        with FakeEndpoint([text_reply("ok")]) as fake:
            events = _events(_service(fake.endpoint))
            (request,) = fake.requests
        assert elsewhere.requests == []
    assert events[-1]["type"] == "message_stop"
    assert _credential_headers(request.headers) == {}
    assert "x-leak" not in request.headers
    assert "x-other" not in request.headers
    assert ENV_KEY not in json.dumps(request.headers)
    assert ENV_TOKEN not in json.dumps(request.headers)


def test_the_runner_removes_every_anthropic_variable_from_its_own_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in LIBRARY_VARIABLES:
        monkeypatch.setenv(name, "set")
    monkeypatch.setenv("anthropic_lower_case", "set")
    monkeypatch.setenv("NOT_ANTHROPIC_X", "kept")
    with FakeEndpoint() as fake:
        _service(fake.endpoint).close()
    assert [n for n in os.environ if n.upper().startswith("ANTHROPIC_")] == []
    assert os.environ["NOT_ANTHROPIC_X"] == "kept"


def test_the_librarys_own_client_would_use_those_variables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # What the test above guards against: built as it builds itself, the library sends the
    # variable's key and custom headers to the variable's base URL.
    with FakeEndpoint([text_reply("elsewhere")]) as elsewhere:
        monkeypatch.setenv("ANTHROPIC_API_KEY", ENV_KEY)
        monkeypatch.setenv("ANTHROPIC_BASE_URL", elsewhere.endpoint)
        monkeypatch.setenv("ANTHROPIC_CUSTOM_HEADERS", CUSTOM_HEADERS)
        _default_events(_default_client())
        (request,) = elsewhere.requests
    assert request.headers["authorization"] == f"Bearer {ENV_KEY}"
    assert request.headers["x-leak"] == "from-the-environment"


def _profile(config_dir: Path, token: str = PROFILE_TOKEN) -> None:
    """An active profile, ``work``, holding ``token``, in the layout the library reads:
    ``active_config`` naming it, ``configs/work.json`` its authentication, and
    ``credentials/work.json`` (owner-only) its token."""
    (config_dir / "configs").mkdir(parents=True)
    (config_dir / "credentials").mkdir()
    (config_dir / "active_config").write_text("work", encoding="utf-8")
    (config_dir / "configs" / "work.json").write_text(
        json.dumps({"authentication": {"type": "user_oauth"}}), encoding="utf-8"
    )
    secret = config_dir / "credentials" / "work.json"
    secret.write_text(json.dumps({"access_token": token, "expires_at": None}), encoding="utf-8")
    secret.chmod(0o600)


def test_an_active_profile_under_anthropic_config_dir_sends_no_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _profile(tmp_path / "anthropic")
    monkeypatch.setenv("ANTHROPIC_CONFIG_DIR", str(tmp_path / "anthropic"))
    with FakeEndpoint([text_reply("ok")]) as fake:
        _events(_service(fake.endpoint))
        (request,) = fake.requests
    assert _credential_headers(request.headers) == {}
    assert PROFILE_TOKEN not in json.dumps(request.headers)


def test_the_librarys_own_client_would_send_that_profiles_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _profile(tmp_path / "anthropic")
    monkeypatch.setenv("ANTHROPIC_CONFIG_DIR", str(tmp_path / "anthropic"))
    with FakeEndpoint([text_reply("ok")]) as fake:
        _default_events(_default_client(base_url=fake.endpoint))
        (request,) = fake.requests
    assert request.headers["authorization"] == f"Bearer {PROFILE_TOKEN}"


def _home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the home directory, and Windows' APPDATA, at ``tmp_path``; the library's default
    config directory there."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData"))
    if sys.platform == "win32":
        return tmp_path / "AppData" / "Anthropic"
    return tmp_path / ".config" / "anthropic"


def test_an_active_profile_in_the_default_config_directory_sends_no_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # No ANTHROPIC_* variable is set, so removing them can't be what keeps this profile out: only
    # the runner's client, a subclass the library runs no discovery for, does.
    _profile(_home(tmp_path, monkeypatch))
    with FakeEndpoint([text_reply("ok")]) as fake:
        _events(_service(fake.endpoint))
        (request,) = fake.requests
    assert _credential_headers(request.headers) == {}
    with FakeEndpoint([text_reply("ok")]) as fake:
        _default_events(_default_client(base_url=fake.endpoint))
        (default,) = fake.requests
    assert default.headers["authorization"] == f"Bearer {PROFILE_TOKEN}"


# Requirement: The credential goes only in the Authorization header


def test_the_credential_is_sent_only_as_a_bearer_authorization_header() -> None:
    with FakeEndpoint([text_reply("ok")]) as fake:
        _events(_service(fake.endpoint, KEY))
        (request,) = fake.requests
    assert request.headers["authorization"] == f"Bearer {KEY}"
    assert "x-api-key" not in request.headers
    others = {k: v for k, v in request.headers.items() if k != "authorization"}
    assert KEY not in json.dumps(others)
    assert KEY not in request.body.decode()
    assert KEY not in request.path


def test_without_a_credential_neither_authorization_nor_x_api_key_is_sent() -> None:
    with FakeEndpoint([text_reply("ok")]) as fake:
        _events(_service(fake.endpoint))
        (request,) = fake.requests
    assert _credential_headers(request.headers) == {}


def test_each_request_is_a_streamed_post_to_v1_messages_below_the_endpoint() -> None:
    with FakeEndpoint([text_reply("ok")]) as fake:
        _events(_service(fake.endpoint + "/gateway/anthropic"))
        (request,) = fake.requests
    assert (request.method, request.path) == ("POST", "/gateway/anthropic/v1/messages")
    assert request.json() == {**PARAMS, "stream": True}


# Requirement: Redirects are never followed


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
def test_a_redirect_is_a_status_error_after_one_request_and_nothing_reaches_its_location(
    status: int,
) -> None:
    with FakeEndpoint([text_reply("elsewhere")]) as elsewhere:
        location = elsewhere.endpoint + "/v1/messages"
        with FakeEndpoint([Reply(status, headers=[("Location", location)], body=b"")]) as fake:
            service = _service(fake.endpoint, KEY)
            with pytest.raises(StatusError) as raised:
                service.stream(PARAMS)
            service.close()
            assert len(fake.requests) == 1
        assert elsewhere.requests == []
    assert raised.value.status == status
    assert raised.value.headers["location"] == location


def test_the_librarys_own_client_would_follow_that_redirect() -> None:
    with FakeEndpoint([text_reply("elsewhere")]) as elsewhere:
        location = elsewhere.endpoint + "/v1/messages"
        with FakeEndpoint([Reply(307, headers=[("Location", location)], body=b"")]) as fake:
            events = _default_events(_default_client(base_url=fake.endpoint, api_key=KEY))
        assert len(elsewhere.requests) == 1
    assert events[-1] == "message_stop"


# Requirement: Every timeout the library applies is one of the runner's named settings


def test_the_library_applies_the_runners_four_named_timeouts() -> None:
    with FakeEndpoint([text_reply("ok")]) as fake:
        service = _service(fake.endpoint)
        timeout = service._client.timeout  # what the library was given
        _events(service)
        (request,) = fake.requests
    assert timeout == httpx2.Timeout(
        connect=CONNECT_TIMEOUT_SECONDS,
        read=STREAM_TIMEOUT_SECONDS,
        write=WRITE_TIMEOUT_SECONDS,
        pool=CONNECT_TIMEOUT_SECONDS,
    )
    # The library tells the service the read timeout it applies: the runner's, not its own.
    assert float(request.headers["x-stainless-read-timeout"]) == STREAM_TIMEOUT_SECONDS


def test_the_librarys_own_read_timeout_would_be_ten_minutes() -> None:
    with FakeEndpoint([text_reply("ok")]) as fake:
        _default_events(_default_client(base_url=fake.endpoint, api_key="x"))
        (request,) = fake.requests
    assert float(request.headers["x-stainless-read-timeout"]) == 600


@pytest.fixture
def silent_server() -> Iterator[str]:
    """An endpoint that takes the connection and the request, and never answers."""
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen()
    host, port = server.getsockname()[:2]
    try:
        yield f"http://{host}:{port}"
    finally:
        server.close()


def test_a_service_that_never_answers_is_abandoned_after_the_stream_timeout(
    silent_server: str,
) -> None:
    service = _service(silent_server, stream_timeout=0.5)
    started = time.monotonic()
    with pytest.raises(NetworkError, match="Timeout"):
        service.stream(PARAMS)
    service.close()
    assert time.monotonic() - started < 10


def test_a_stream_held_open_after_its_first_event_is_a_network_error_after_the_stream_timeout() -> (
    None
):
    with FakeEndpoint([Reply(lines=sse([start(), Hold()]))]) as fake:
        service = _service(fake.endpoint, stream_timeout=0.5)
        opened = service.stream(PARAMS)
        assert next(opened.events)["type"] == "message_start"
        started = time.monotonic()
        with pytest.raises(NetworkError):
            list(opened.events)
        assert time.monotonic() - started < 10
        service.close()
        assert fake.wait_for_client_to_close(5)


# What the runner sees: one of a closed set of failures


def test_a_200_that_isnt_a_stream_is_not_a_stream_error_with_its_body() -> None:
    with FakeEndpoint([Reply(200, body=b'{"id": "msg_1"}')]) as fake:
        service = _service(fake.endpoint)
        with pytest.raises(NotAStreamError) as raised:
            service.stream(PARAMS)
        service.close()
    assert (raised.value.status, raised.value.content_type) == (200, "application/json")
    assert raised.value.body == b'{"id": "msg_1"}'


def test_an_error_status_carries_its_headers_type_message_and_body() -> None:
    reply = error_reply(429, "slow down", "rate_limit_error", headers=[("Retry-After", "2")])
    with FakeEndpoint([reply]) as fake:
        service = _service(fake.endpoint)
        with pytest.raises(StatusError) as raised:
            service.stream(PARAMS)
        service.close()
    failure = raised.value
    assert (failure.status, failure.error_type, failure.message) == (
        429,
        "rate_limit_error",
        "slow down",
    )
    assert failure.headers["retry-after"] == "2"
    assert json.loads(failure.body)["error"]["message"] == "slow down"
    assert failure.in_stream is False


def test_an_error_event_in_the_stream_is_a_status_error_in_the_stream() -> None:
    with FakeEndpoint([stream_error_reply("overloaded_error", "Overloaded")]) as fake:
        service = _service(fake.endpoint)
        opened = service.stream(PARAMS)
        with pytest.raises(StatusError) as raised:
            list(opened.events)
        service.close()
    assert opened.status == 200
    failure = raised.value
    assert failure.in_stream is True
    assert (failure.error_type, failure.message) == ("overloaded_error", "Overloaded")


def test_an_event_whose_data_isnt_json_is_unreadable() -> None:
    lines = [*sse([start()]), "event: message_delta", "data: not json", ""]
    with FakeEndpoint([Reply(lines=lines)]) as fake:
        service = _service(fake.endpoint)
        opened = service.stream(PARAMS)
        with pytest.raises(UnreadableError, match="isn't JSON"):
            list(opened.events)
        service.close()


def test_a_refused_connection_is_a_network_error() -> None:
    with FakeEndpoint() as fake:
        endpoint = fake.endpoint
    service = _service(endpoint)
    with pytest.raises(NetworkError):
        service.stream(PARAMS)
    service.close()


def test_each_event_is_the_librarys_parsed_event_as_a_dict() -> None:
    with FakeEndpoint([text_reply("Hello.")]) as fake:
        events = _events(_service(fake.endpoint))
    assert events[0]["type"] == "message_start"
    assert events[0]["message"]["model"] == "fake-model"
    deltas = [e["delta"]["text"] for e in events if e["type"] == "content_block_delta"]
    assert "".join(deltas) == "Hello."


# Requirement: The library's own logging stays out of the run's output


@pytest.fixture
def library_loggers() -> Iterator[None]:
    """Each library logger's handlers, level and propagation, restored after the test."""
    saved = [
        (logger, list(logger.handlers), logger.level, logger.propagate)
        for logger in (logging.getLogger(name) for name in LIBRARY_LOGGERS)
    ]
    yield
    for logger, handlers, level, propagate in saved:
        logger.handlers = handlers
        logger.setLevel(level)
        logger.propagate = propagate


@pytest.mark.usefixtures("library_loggers")
def test_a_debug_record_asked_for_reaches_neither_standard_output_nor_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # What ANTHROPIC_LOG=debug does: the library's logger at DEBUG, with a handler that prints.
    library = logging.getLogger("anthropic")
    library.setLevel(logging.DEBUG)
    library.addHandler(logging.StreamHandler(sys.stdout))
    stream = io.StringIO()
    quiet_library_logging(Mask(KEY), stream)
    library.debug("Request options: %s", {"headers": {"Authorization": f"Bearer {KEY}"}})
    logging.getLogger("anthropic._base_client").info("HTTP Request: POST")
    logging.getLogger("httpx2").debug("sending")
    assert stream.getvalue() == ""
    assert capsys.readouterr().out == ""


@pytest.mark.usefixtures("library_loggers")
def test_a_warning_reaches_the_stream_as_one_line_masked_and_cut(
    capsys: pytest.CaptureFixture[str],
) -> None:
    stream = io.StringIO()
    quiet_library_logging(Mask(KEY), stream)
    logging.getLogger("anthropic._client").warning("key %s\nthen %s", KEY, "x" * 5000)
    written = stream.getvalue()
    assert written.count("\n") == 1
    assert written.startswith("anthropic runner: library warning: key ")
    assert MASK in written
    assert KEY not in written
    assert written.rstrip("\n").endswith("bytes left out)")
    assert len(written.encode()) < LIBRARY_LOG_MAX_BYTES + 200
    assert capsys.readouterr().out == ""
