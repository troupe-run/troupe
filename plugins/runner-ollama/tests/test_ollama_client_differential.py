"""What the Ollama client does, written down as data, so moving it onto another HTTP library can be
shown to change nothing (ollama-library design D8).

Each case scripts the fake endpoint, makes one call, and states what the call returned or raised and
what the fake received. The cases passed on the client built on http.client before the move to
httpx2, unchanged. A message that quotes the transport's own exception text is matched by its prefix
only, since that text is the library's.
"""

import json
import os
import socket
import ssl
import threading
import time
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar

import httpcore2
import pytest

from fake_ollama import Answer, FakeOllama, Line, Settings, done, final, message, serving
from troupe_runner_ollama.client import (
    Client,
    EngineError,
    RetryableError,
    StoppedError,
    UnreachableError,
    _RecordedStream,
    _Sockets,
)

BODY = b'{"model":"fake","messages":[{"role":"user","content":"hi \xc3\xa9"}],"stream":true}'
"""A chat request's exact bytes, with a character that isn't ASCII."""

LIMIT = 1024
"""The line limit the line-length cases give the client."""

IDLE = 0.3
"""The idle timeout the silence cases give the client."""


@dataclass(frozen=True)
class Returned:
    """The call returned: the lines ``chat`` yielded, or the value ``version`` or ``show`` gave."""

    value: object


@dataclass(frozen=True)
class Raised:
    """The call raised ``kind``, with these fields; ``message`` is matched whole, or by
    ``message_prefix`` when it quotes the transport's own text."""

    kind: type[Exception]
    message: str | None = None
    message_prefix: str | None = None
    reason: str | None = None
    status: int | None = None
    body: bytes | None = None


@dataclass(frozen=True)
class Sent:
    """A request the fake received."""

    method_path: str
    body: bytes = b""


@dataclass(frozen=True)
class Case:
    name: str
    call: str
    """``chat``, ``version``, ``show:<model>``, or ``closed-chat`` (chat on a closed client)."""
    expect: Returned | Raised
    sent: Sequence[Sent]
    answers: Sequence[Answer] = ()
    settings: Settings = field(default_factory=Settings)


def _line(data: dict[str, object]) -> bytes:
    return json.dumps(data).encode()


A = _line(message("a"))
DONE = _line(done())
LONG = b'{"x":"' + b"a" * 5000 + b'"}'
EXACT = b'{"x":"' + b"a" * (LIMIT - 8) + b'"}'
FAILED_TO_LOAD = b'{"error":"model failed to load"}'
CHAT = Sent("POST /api/chat", BODY)

CASES: list[Case] = [
    Case("a streamed answer", "chat", Returned([A, DONE]), [CHAT], [Answer([A, DONE])]),
    Case(
        "an answer whose lines aren't ASCII or UTF-8",
        "chat",
        Returned([b'{"message":{"content":"caf\xc3\xa9 \xff"}}', DONE]),
        [CHAT],
        [Answer([b'{"message":{"content":"caf\xc3\xa9 \xff"}}', DONE])],
    ),
    Case(
        "an error line, which the conversation reads",
        "chat",
        Returned([A, b'{"error":"boom"}']),
        [CHAT],
        [Answer([A, b'{"error":"boom"}'])],
    ),
    *(
        Case(
            f"status {status}",
            "chat",
            Raised(
                EngineError,
                f"Ollama answered status {status}: model failed to load",
                status=status,
                body=FAILED_TO_LOAD,
            ),
            [CHAT],
            [Answer(status=status, body=FAILED_TO_LOAD)],
        )
        for status in (400, 401, 403, 404, 429, 501)
    ),
    *(
        Case(
            f"status {status}",
            "chat",
            Raised(
                RetryableError,
                f"Ollama answered status {status}: model failed to load",
                reason="server",
                body=FAILED_TO_LOAD,
            ),
            [CHAT],
            [Answer(status=status, body=FAILED_TO_LOAD)],
        )
        for status in (500, 502, 503, 504)
    ),
    Case(
        "an error status with a body that isn't JSON",
        "chat",
        Raised(RetryableError, "Ollama answered status 502: bad gateway", reason="server"),
        [CHAT],
        [Answer(status=502, body=b"bad gateway")],
    ),
    Case(
        "a redirect, never followed",
        "chat",
        Raised(EngineError, "Ollama answered status 307", status=307, body=b""),
        [CHAT],
        [Answer(status=307, headers={"Location": "http://127.0.0.1:9/api/chat"})],
    ),
    Case(
        "a connection closed part-way, which ends the lines",
        "chat",
        Returned([A]),
        [CHAT],
        [Answer([A, _line(message("b")), DONE], close_after=1)],
    ),
    Case(
        "a connection closed before any line",
        "chat",
        Returned([]),
        [CHAT],
        [Answer([A, DONE], close_after=0)],
    ),
    Case(
        "a stream that goes silent",
        "chat",
        Raised(RetryableError, f"Ollama sent nothing for {IDLE:g}s", reason="network"),
        [CHAT],
        [Answer([A], silent=True)],
    ),
    Case(
        "a request answered with nothing at all",
        "chat",
        Raised(RetryableError, f"Ollama sent nothing for {IDLE:g}s", reason="network"),
        [CHAT],
        [Answer(before_headers=True)],
    ),
    Case(
        "a line over the limit",
        "chat",
        Raised(RetryableError, f"Ollama sent a line longer than {LIMIT} bytes", reason="network"),
        [CHAT],
        [Answer([LONG, DONE])],
    ),
    Case(
        "a line of exactly the limit",
        "chat",
        Returned([EXACT, DONE]),
        [CHAT],
        [Answer([EXACT, DONE])],
    ),
    Case("a closed client", "closed-chat", Raised(StoppedError), [], [Answer([A, DONE])]),
    Case("Ollama's version", "version", Returned("0.12.6"), [Sent("GET /api/version")]),
    Case(
        "no version endpoint",
        "version",
        Raised(UnreachableError, "/api/version answered status 404 without Ollama's version"),
        [Sent("GET /api/version")],
        settings=Settings(version=None),
    ),
    Case(
        "a version answer that isn't Ollama's",
        "version",
        Raised(UnreachableError, "/api/version answered status 200 without Ollama's version"),
        [Sent("GET /api/version")],
        settings=Settings(version_body=b"<html>hello</html>"),
    ),
    Case(
        "a redirected version request, never followed",
        "version",
        Raised(UnreachableError, "/api/version answered status 307 without Ollama's version"),
        [Sent("GET /api/version")],
        settings=Settings(version_redirect="http://127.0.0.1:9/api/version"),
    ),
    Case(
        "a silent preflight",
        "version",
        Raised(UnreachableError, message_prefix=""),
        [Sent("GET /api/version")],
        settings=Settings(silent_preflight=True),
    ),
    Case(
        "a model Ollama has",
        "show:fake",
        Returned(
            {
                "capabilities": ["completion", "tools"],
                "model_info": {"general.architecture": "fake", "fake.context_length": 40960},
            }
        ),
        [Sent("POST /api/show", b'{"model": "fake"}')],
    ),
    Case(
        "a model Ollama hasn't",
        "show:missing",
        Returned(None),
        [Sent("POST /api/show", b'{"model": "missing"}')],
    ),
]


def _call(client: Client, case: Case) -> object:
    if case.call == "chat":
        return list(client.chat(BODY))
    if case.call == "closed-chat":
        client.close()
        return list(client.chat(BODY))
    if case.call == "version":
        return client.version(IDLE)
    model = case.call.removeprefix("show:")
    return client.show(model, IDLE)


def _received(fake: FakeOllama) -> list[Sent]:
    methods = {"/api/version": "GET"}
    return [Sent(f"{methods.get(r.path, 'POST')} {r.path}", r.body) for r in fake.requests]


@pytest.mark.parametrize("case", CASES, ids=[case.name for case in CASES])
def test_the_client_does_what_it_did_before_the_move_to_httpx2(case: Case) -> None:
    with serving(case.answers, case.settings) as fake:
        client = Client(fake.url, idle_timeout=IDLE, line_max_bytes=LIMIT)
        if isinstance(case.expect, Returned):
            assert _call(client, case) == case.expect.value
        else:
            expected = case.expect
            with pytest.raises(expected.kind) as caught:
                _call(client, case)
            error = caught.value
            if expected.message is not None:
                assert str(error) == expected.message
            if expected.message_prefix is not None:
                assert str(error).startswith(expected.message_prefix)
            for name in ("reason", "status", "body"):
                wanted = getattr(expected, name)
                if wanted is not None:
                    assert getattr(error, name) == wanted, name
        assert _received(fake) == list(case.sent)


def test_a_refused_chat_connection_is_a_network_retry_naming_the_failure(
    free_port: Callable[[], int],
) -> None:
    with pytest.raises(RetryableError) as caught:
        list(Client(f"http://127.0.0.1:{free_port()}").chat(BODY))
    assert caught.value.reason == "network"
    assert caught.value.message.startswith("couldn't reach Ollama: ")


def test_a_refused_preflight_connection_is_unreachable(free_port: Callable[[], int]) -> None:
    with pytest.raises(UnreachableError):
        Client(f"http://127.0.0.1:{free_port()}").version(5)


# The guarantees a client library could otherwise break (spec: ollama-runner, "The runner's HTTP
# client takes nothing from the environment"; runner-protocol, #333).


@pytest.fixture
def free_port() -> Callable[[], int]:
    def pick() -> int:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port: int = sock.getsockname()[1]
            return port

    return pick


@pytest.fixture
def elsewhere() -> Iterator[FakeOllama]:
    """A second fake, where a redirect points: it must never be reached."""
    with serving([final("elsewhere")]) as fake:
        yield fake


def test_a_redirected_chat_never_reaches_the_other_address(elsewhere: FakeOllama) -> None:
    answer = Answer(status=307, headers={"Location": f"{elsewhere.url}/api/chat"})
    with serving([answer]) as fake:
        with pytest.raises(EngineError) as caught:
            list(Client(fake.url).chat(BODY))
        assert caught.value.status == 307
    assert elsewhere.requests == []


def test_a_redirected_preflight_never_reaches_the_other_address(elsewhere: FakeOllama) -> None:
    settings = Settings(version_redirect=f"{elsewhere.url}/api/version")
    with serving(settings=settings) as fake, pytest.raises(UnreachableError):
        Client(fake.url).version(5)
    assert elsewhere.requests == []


def test_proxy_and_netrc_settings_change_nothing_the_client_sends(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, free_port: Callable[[], int]
) -> None:
    # A proxy that isn't there: a client that used it couldn't connect. A .netrc login for the
    # fake's host: a client that read it would send it as Basic auth.
    nowhere = f"http://127.0.0.1:{free_port()}"
    netrc = tmp_path / "netrc"
    netrc.write_text("machine 127.0.0.1 login someone password canary-secret\n")
    if os.name != "nt":
        netrc.chmod(0o600)
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "all_proxy"):
        monkeypatch.setenv(name, nowhere)
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.delenv("no_proxy", raising=False)
    monkeypatch.setenv("NETRC", str(netrc))
    with serving([final("hi")]) as fake:
        client = Client(fake.url)
        assert client.version(5) == "0.12.6"
        assert client.show("fake", 5) is not None
        assert len(list(client.chat(BODY))) == 2
        assert [r.path for r in fake.requests] == ["/api/version", "/api/show", "/api/chat"]
        for request in fake.requests:
            assert "authorization" not in request.headers
            assert "proxy-authorization" not in request.headers


# Closing from another thread (design D4)

BOUND = 5.0
"""The idle timeout the close tests give the client, so a close that doesn't wake the read fails
in seconds rather than waiting out the runner's default."""


def _closed_within(client: Client, lines: Iterator[bytes], seconds: float) -> float:
    """Close ``client`` from another thread after a moment, and how long ``lines`` took to stop."""
    timer = threading.Timer(0.2, client.close)
    timer.start()
    started = time.monotonic()
    with pytest.raises(StoppedError):
        next(lines)
    took = time.monotonic() - started
    timer.join()
    assert took < seconds
    return took


def test_close_wakes_a_request_still_waiting_for_its_answer() -> None:
    # Ollama sends nothing, not even a status, while it loads a model.
    with serving([Answer(before_headers=True)]) as fake:
        client = Client(fake.url, idle_timeout=BOUND)
        _closed_within(client, client.chat(BODY), 1.2)
        assert fake.closed_by_client.wait(5)


def test_close_wakes_a_stream_held_open() -> None:
    with serving([Answer([A, Line(b"{}", delay=30)])]) as fake:
        client = Client(fake.url, idle_timeout=BOUND)
        lines = client.chat(BODY)
        assert next(lines) == A
        _closed_within(client, lines, 1.2)
        assert fake.closed_by_client.wait(5)


# TLS (design D3)


class _RefusingContext(ssl.SSLContext):
    """The default context's settings, but a handshake through it is recorded and refused."""

    wrapped: ClassVar[list[str | None]] = []

    def wrap_socket(self, *args: Any, **kwargs: Any) -> ssl.SSLSocket:  # noqa: ANN401
        _RefusingContext.wrapped.append(kwargs.get("server_hostname"))
        raise ssl.SSLError("refused by the test's context")


def test_an_https_endpoint_goes_through_the_runners_own_tls_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The runner's context is ssl.create_default_context(), what http.client used, not httpx2's
    # truststore default: a handshake through any other context would never reach this one.
    _RefusingContext.wrapped.clear()

    def refusing() -> ssl.SSLContext:
        return _RefusingContext(ssl.PROTOCOL_TLS_CLIENT)

    monkeypatch.setattr(ssl, "create_default_context", refusing)
    with serving() as fake:
        endpoint = fake.url.replace("http://", "https://")
        with pytest.raises(UnreachableError, match="refused by the test's context"):
            Client(endpoint).version(5)
    assert _RefusingContext.wrapped == ["127.0.0.1"]


class _PlainStream(httpcore2.NetworkStream):
    """A stream over one socket, standing in for httpcore2's own after its TLS handshake."""

    def __init__(self, sock: socket.socket) -> None:
        self.sock = sock

    def get_extra_info(self, info: str) -> Any:  # noqa: ANN401
        return self.sock if info == "socket" else None


class _Upgrading(_PlainStream):
    """A connection whose TLS handshake gives a stream on another socket, as wrap_socket does."""

    def __init__(self, sock: socket.socket, upgraded: socket.socket) -> None:
        super().__init__(sock)
        self.upgraded = upgraded

    def start_tls(
        self,
        ssl_context: ssl.SSLContext,
        server_hostname: str | None = None,
        timeout: float | None = None,
    ) -> httpcore2.NetworkStream:
        return _PlainStream(self.upgraded)


def test_close_shuts_down_the_socket_tls_wraps_a_connection_in() -> None:
    # TLS hands the connection to a new socket; close has to shut that one, not only the first.
    sockets = _Sockets()
    plain, plain_peer = socket.socketpair()
    upgraded, upgraded_peer = socket.socketpair()
    with plain, plain_peer, upgraded, upgraded_peer:
        sockets.add(plain)
        stream = _RecordedStream(_Upgrading(plain, upgraded), sockets)
        stream.start_tls(ssl.create_default_context(), "ollama.example")
        sockets.close()
        upgraded_peer.settimeout(5)
        assert upgraded_peer.recv(1) == b""  # the peer sees the upgraded socket shut down


# Bytes as Ollama sent them (design D3, D5)


def test_every_request_asks_for_its_answer_unencoded() -> None:
    with serving([final("hi")]) as fake:
        client = Client(fake.url)
        client.version(5)
        client.show("fake", 5)
        list(client.chat(BODY))
    assert [(r.path, r.headers.get("accept-encoding")) for r in fake.requests] == [
        ("/api/version", "identity"),
        ("/api/show", "identity"),
        ("/api/chat", "identity"),
    ]


def test_an_answer_sent_encoded_is_refused_as_a_network_failure_never_read_as_lines() -> None:
    answer = Answer([A, DONE], headers={"Content-Encoding": "gzip"})
    with serving([answer]) as fake:
        lines = Client(fake.url).chat(BODY)
        with pytest.raises(RetryableError) as caught:
            next(lines)
    assert caught.value.reason == "network"
    assert caught.value.message == (
        "Ollama sent its answer encoded as 'gzip', though the runner asked for it unencoded"
    )
