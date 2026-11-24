"""How the runner reaches a service through the openai package, checked in this process: which
endpoints count as this machine, a credential over plain HTTP to another host refused, where
requests go and through which proxy, the library's timeouts, and the caps on a stream's lines and
on a body read whole (spec: openai-runner, "A credential never travels in the clear", "Every
timeout the library applies is one of the runner's named settings", "A stream's lines are capped
below the library"; openai-library design D2-D4a).

Its tests that start a process, open a socket or use a git theatre are in
integration/test_openai_service_integration.py."""

import gzip
import json
from collections.abc import Iterator

import httpx2
import pytest

from openai_service_shared import KEY, PARAMS
from troupe_runner_openai import defaults
from troupe_runner_openai.service import (
    EndpointError,
    NetworkError,
    NotAStreamError,
    Service,
    StatusError,
    is_loopback,
    parse_endpoint,
    proxy_for,
)

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


@pytest.mark.parametrize(
    "shape",
    [
        "https://user:{}@example.com/v1",
        "https://{}@example.com/v1",
        "ftp://user:{}@example.com/v1",
        "https://user:{}@example.com:99999/v1",
    ],
)
def test_an_endpoint_refused_with_user_info_isnt_repeated(shape: str) -> None:
    # The SDK refuses these first; the runner's own check never repeats one either (#323).
    canary = "q7ZxW9pL4vR2canary"
    with pytest.raises(EndpointError) as raised:
        parse_endpoint(shape.format(canary))
    assert canary not in str(raised.value)


@pytest.mark.parametrize(
    ("endpoint", "responses"),
    [
        ("https://api.openai.com/v1", "https://api.openai.com/v1/responses"),
        ("https://api.openai.com/v1/", "https://api.openai.com/v1/responses"),
        # // is a path (runtime-checks design D1), so requests stay below it, never at the root.
        ("http://127.0.0.1:8000//", "http://127.0.0.1:8000//responses"),
        ("http://127.0.0.1:8000///", "http://127.0.0.1:8000///responses"),
    ],
)
def test_requests_go_below_the_endpoint(endpoint: str, responses: str) -> None:
    assert parse_endpoint(endpoint).responses_url == responses


@pytest.mark.parametrize(
    ("endpoint", "responses"),
    [
        ("https://api.openai.com/v1", "https://api.openai.com/v1/responses"),
        ("https://api.openai.com/v1/", "https://api.openai.com/v1/responses"),
        ("http://127.0.0.1:8000//", "http://127.0.0.1:8000//responses"),
    ],
)
def test_the_library_sends_each_request_where_the_endpoint_says(
    endpoint: str, responses: str
) -> None:
    seen: list[str] = []

    def answer(request: httpx2.Request) -> httpx2.Response:
        seen.append(str(request.url))
        return httpx2.Response(404, json={"error": {"message": "x", "code": "nope"}})

    service = Service(parse_endpoint(endpoint), KEY, transport=httpx2.MockTransport(answer))
    with pytest.raises(StatusError):
        service.stream(PARAMS)
    assert seen == [responses] == [parse_endpoint(endpoint).responses_url]


def test_another_hosts_proxy_is_the_one_urllib_would_choose(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.example:3128")
    monkeypatch.setenv("https_proxy", "http://proxy.example:3128")
    for name in ("NO_PROXY", "no_proxy"):
        monkeypatch.setenv(name, "")
    assert proxy_for(parse_endpoint("https://api.openai.com/v1")) == "http://proxy.example:3128"
    for name in ("NO_PROXY", "no_proxy"):
        monkeypatch.setenv(name, "api.openai.com")
    assert proxy_for(parse_endpoint("https://api.openai.com/v1")) is None


def test_the_librarys_timeouts_are_the_runners_named_settings() -> None:
    service = Service(parse_endpoint("http://127.0.0.1:9/v1"), None)
    timeout = service._client.timeout  # what the library was given
    assert isinstance(timeout, httpx2.Timeout)
    assert (timeout.connect, timeout.read, timeout.write, timeout.pool) == (
        defaults.CONNECT_TIMEOUT_SECONDS,
        defaults.STREAM_TIMEOUT_SECONDS,
        defaults.WRITE_TIMEOUT_SECONDS,
        defaults.CONNECT_TIMEOUT_SECONDS,
    )
    assert service._client.max_retries == 0


# The line cap (design D4a)


def _stream_of(*lines: bytes) -> Iterator[bytes]:
    yield from lines


def test_a_line_past_the_cap_is_a_network_error_naming_the_limit_before_more_is_read() -> None:
    read: list[int] = []

    def answer(_: httpx2.Request) -> httpx2.Response:
        def body() -> Iterator[bytes]:
            yield b'data: {"type": "x"}\n\n'
            for _ in range(1000):
                read.append(1)
                yield b"a" * 64

        return httpx2.Response(200, headers={"content-type": "text/event-stream"}, content=body())

    service = Service(
        parse_endpoint("http://127.0.0.1:9/v1"),
        None,
        transport=httpx2.MockTransport(answer),
        line_max_bytes=256,
    )
    opened = service.stream(PARAMS)
    with pytest.raises(NetworkError, match=r"longer than 256 bytes.*STREAM_LINE_MAX_BYTES"):
        list(opened.events)
    assert len(read) <= 256 // 64 + 1


def test_lines_up_to_the_cap_are_read_however_they_arrive() -> None:
    line = b'data: {"type": "x", "pad": "' + b"b" * 200 + b'"}'
    chunks = [line[:7], line[7:150], line[150:] + b"\r\n\r", b"\n"]

    def answer(_: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200, headers={"content-type": "text/event-stream"}, content=_stream_of(*chunks)
        )

    service = Service(
        parse_endpoint("http://127.0.0.1:9/v1"),
        None,
        transport=httpx2.MockTransport(answer),
        line_max_bytes=len(line),
    )
    assert [e["type"] for e in service.stream(PARAMS).events] == ["x"]


def test_the_cap_by_default_is_the_named_setting() -> None:
    assert defaults.STREAM_LINE_MAX_BYTES == 16 * 1024 * 1024


@pytest.mark.parametrize("encoding", ["gzip", "deflate", "br", "x-gzip"])
def test_a_response_sent_encoded_is_refused_before_its_body_is_read(encoding: str) -> None:
    """A gzip body whose one line is past the cap once decoded, though only a few hundred bytes
    on the wire: the transport can't count decoded lines, so it refuses the encoding (review of
    #440)."""
    decoded = b'data: {"type": "x", "pad": "' + b"a" * 100_000 + b'"}\n\n'
    read: list[int] = []

    def body() -> Iterator[bytes]:
        read.append(1)
        yield gzip.compress(decoded)

    def answer(_: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            headers={"content-type": "text/event-stream", "content-encoding": encoding},
            content=body(),
        )

    service = Service(
        parse_endpoint("http://127.0.0.1:9/v1"),
        None,
        transport=httpx2.MockTransport(answer),
        line_max_bytes=1024,
    )
    with pytest.raises(NetworkError, match=rf"encoded \({encoding}\).*STREAM_LINE_MAX_BYTES"):
        list(service.stream(PARAMS).events)
    assert read == []


def test_a_response_whose_encoding_is_identity_is_read() -> None:
    def answer(_: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            headers={"content-type": "text/event-stream", "content-encoding": "identity"},
            content=b'data: {"type": "x"}\n\n',
        )

    service = Service(
        parse_endpoint("http://127.0.0.1:9/v1"), None, transport=httpx2.MockTransport(answer)
    )
    assert [e["type"] for e in service.stream(PARAMS).events] == ["x"]


def _encoded_error(status: int, encoding: str, body: bytes) -> Service:
    def answer(_: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            status,
            headers={"content-type": "application/json", "content-encoding": encoding},
            content=body,
        )

    return Service(
        parse_endpoint("http://127.0.0.1:9/v1"), None, transport=httpx2.MockTransport(answer)
    )


def test_an_error_sent_gzipped_keeps_its_status_and_decoded_body() -> None:
    body = json.dumps({"error": {"message": "Incorrect API key provided", "code": None}})
    service = _encoded_error(401, "gzip", gzip.compress(body.encode()))
    with pytest.raises(StatusError) as raised:
        service.stream(PARAMS)
    assert raised.value.status == 401
    assert json.loads(raised.value.body)["error"]["message"] == "Incorrect API key provided"
    assert "content-encoding" not in raised.value.headers


def test_an_errors_encoded_body_decodes_to_no_more_than_the_body_limit() -> None:
    bomb = gzip.compress(b"a" * (defaults.ERROR_BODY_MAX_BYTES * 8))
    with pytest.raises(StatusError) as raised:
        _encoded_error(500, "gzip", bomb).stream(PARAMS)
    assert raised.value.status == 500
    assert len(raised.value.body) <= defaults.ERROR_BODY_MAX_BYTES


def test_an_error_in_an_encoding_zlib_cant_read_keeps_its_status_and_raw_body() -> None:
    with pytest.raises(StatusError) as raised:
        _encoded_error(404, "br", b"\x8b\x00not-brotli").stream(PARAMS)
    assert raised.value.status == 404
    assert raised.value.body == b"\x8b\x00not-brotli"


def _endless(status: int, content_type: str, read: list[int]) -> httpx2.MockTransport:
    """A transport answering ``status`` with a body of short lines that never ends, counting
    each piece it's asked for."""

    def answer(_: httpx2.Request) -> httpx2.Response:
        def body() -> Iterator[bytes]:
            while True:
                read.append(1)
                yield b"short line\n"

        return httpx2.Response(status, headers={"content-type": content_type}, content=body())

    return httpx2.MockTransport(answer)


@pytest.mark.parametrize("status", [401, 500])
def test_an_error_body_of_many_short_lines_is_read_no_further_than_the_body_limit(
    status: int,
) -> None:
    """Review of #440: the line cap bounds one line, not a whole body read at once."""
    read: list[int] = []
    service = Service(
        parse_endpoint("http://127.0.0.1:9/v1"),
        None,
        transport=_endless(status, "application/json", read),
        body_max_bytes=1000,
    )
    with pytest.raises(StatusError) as raised:
        service.stream(PARAMS)
    assert raised.value.status == status
    assert len(raised.value.body) == 1000
    assert len(read) <= 1000 // len(b"short line\n") + 1


def test_a_2xx_body_that_isnt_a_stream_is_read_no_further_than_the_body_limit() -> None:
    read: list[int] = []
    service = Service(
        parse_endpoint("http://127.0.0.1:9/v1"),
        None,
        transport=_endless(200, "application/json", read),
        body_max_bytes=1000,
    )
    with pytest.raises(NotAStreamError) as raised:
        service.stream(PARAMS)
    assert len(raised.value.body) == 1000
    assert len(read) <= 1000 // len(b"short line\n") + 1


def test_the_body_limit_by_default_is_the_named_setting() -> None:
    assert defaults.ERROR_BODY_MAX_BYTES == 1024 * 1024
