"""The fake Ollama plays what it's scripted to, so the runner's tests can trust it
(local-model-runner design D12). Driven with plain http.client, not the runner's client."""

import contextlib
import http.client
import json
import os
import socket
import struct
import sys
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest

from fake_ollama import Answer, FakeOllama, Line, Settings, done, final, message, serving

HANDLER_DONE_WITHIN = 10.0
"""Seconds for the fake's handler to reach its error handling after a client's request."""

CLOSE_SEEN_WITHIN = 5.0
"""Seconds for the fake to see a client close a connection it's holding: it looks every
POLL_SECONDS, so this is room for a loaded machine, not the time it takes."""


FD_SETSIZE = 1024
"""select.select refuses a descriptor numbered this or higher on Linux and macOS."""


@contextmanager
def descriptors_past_fd_setsize() -> Iterator[None]:
    """Hold enough descriptors open that every new one is numbered past FD_SETSIZE, as in a test
    worker that has run a thousand tests (#301)."""
    if sys.platform == "win32":  # Windows numbers its sockets otherwise, and select takes them
        raise NotImplementedError("descriptor numbers are a POSIX limit")
    else:
        import resource

        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        wanted = FD_SETSIZE + 200
        if soft < wanted:
            resource.setrlimit(resource.RLIMIT_NOFILE, (wanted, hard))
        held = [os.open(os.devnull, os.O_RDONLY) for _ in range(FD_SETSIZE + 50)]
        try:
            yield
        finally:
            for descriptor in held:
                os.close(descriptor)
            resource.setrlimit(resource.RLIMIT_NOFILE, (soft, hard))


def _post(url: str, path: str, body: object) -> http.client.HTTPResponse:
    host, port = url.removeprefix("http://").split(":")
    connection = http.client.HTTPConnection(host, int(port), timeout=10)
    connection.request("POST", path, body=json.dumps(body).encode())
    return connection.getresponse()


def test_it_answers_version_and_show_from_its_settings() -> None:
    with serving() as fake:
        host, port = fake.url.removeprefix("http://").split(":")
        connection = http.client.HTTPConnection(host, int(port), timeout=10)
        connection.request("GET", "/api/version")
        assert json.loads(connection.getresponse().read()) == {"version": "0.12.6"}
        assert _post(fake.url, "/api/show", {"model": "fake"}).status == 200
        missing = _post(fake.url, "/api/show", {"model": "other"})
        assert missing.status == 404
        assert json.loads(missing.read()) == {"error": "model 'other' not found"}


def test_it_streams_each_scripted_answer_in_turn_and_records_each_request() -> None:
    with serving([final("one"), final("two")]) as fake:
        first = _post(fake.url, "/api/chat", {"n": 1}).read().splitlines()
        second = _post(fake.url, "/api/chat", {"n": 2}).read().splitlines()
        assert json.loads(first[0])["message"]["content"] == "one"
        assert json.loads(first[-1])["done"] is True
        assert json.loads(second[0])["message"]["content"] == "two"
        assert fake.chats() == [{"n": 1}, {"n": 2}]


def test_a_status_answer_sends_its_body() -> None:
    with serving([Answer(status=503, body=b'{"error": "busy"}')]) as fake:
        response = _post(fake.url, "/api/chat", {})
        assert response.status == 503
        assert response.read() == b'{"error": "busy"}'


def test_a_delay_holds_back_its_line() -> None:
    with serving([Answer([Line(b'{"a": 1}', delay=0.3), done()])]) as fake:
        started = time.monotonic()
        _post(fake.url, "/api/chat", {}).read()
        assert time.monotonic() - started >= 0.3


def test_a_close_part_way_ends_the_stream_without_its_last_chunk() -> None:
    with serving([Answer([message("a"), message("b"), done()], close_after=1)]) as fake:
        response = _post(fake.url, "/api/chat", {})
        first = response.readline()
        assert json.loads(first)["message"]["content"] == "a"
        try:
            rest = response.read()
        except http.client.IncompleteRead as error:
            rest = error.partial
        assert b'"b"' not in rest


def test_it_notices_a_client_that_closes_while_it_streams_slowly() -> None:
    with serving([Answer([message("a"), Line(b"{}", delay=10)])]) as fake:
        host, port = fake.url.removeprefix("http://").split(":")
        sock = socket.create_connection((host, int(port)))
        sock.sendall(b"POST /api/chat HTTP/1.1\r\nHost: x\r\nContent-Length: 2\r\n\r\n{}")
        sock.recv(4096)
        sock.close()
        assert fake.closed_by_client.wait(5)


def test_a_silent_answer_waits_until_the_client_goes() -> None:
    with serving([Answer([message("a")], silent=True)]) as fake:
        response = _post(fake.url, "/api/chat", {})
        response.readline()
        response.close()
        assert fake.closed_by_client.wait(5)


def test_preflight_can_be_made_silent() -> None:
    with serving(settings=Settings(silent_preflight=True)) as fake:
        host, port = fake.url.removeprefix("http://").split(":")
        connection = http.client.HTTPConnection(host, int(port), timeout=0.3)
        connection.request("GET", "/api/version")
        try:
            connection.getresponse()
        except TimeoutError:
            pass
        else:
            raise AssertionError("the silent preflight answered")


def test_a_done_line_holds_a_cached_count_only_when_given_one() -> None:
    assert done(cached=4)["prompt_eval_cached_count"] == 4
    assert "prompt_eval_cached_count" not in done()


@pytest.mark.skipif(sys.platform == "win32", reason="Windows has no descriptor-number limit")
def test_a_held_answer_sees_the_client_close_on_a_descriptor_past_fd_setsize() -> None:
    with (
        descriptors_past_fd_setsize(),
        serving([Answer([message("a"), Line(b"{}", delay=60)])]) as fake,
    ):
        host, port = fake.url.removeprefix("http://").split(":")
        client = socket.create_connection((host, int(port)), timeout=10)
        assert client.fileno() >= FD_SETSIZE
        client.sendall(b"POST /api/chat HTTP/1.1\r\nHost: fake\r\nContent-Length: 2\r\n\r\n{}")
        received = b""
        while b'"a"' not in received:  # the first line is in: the fake now holds the next one
            chunk = client.recv(4096)
            assert chunk, "the fake closed the connection"
            received += chunk
        client.close()
        assert fake.closed_by_client.wait(CLOSE_SEEN_WITHIN)


def test_a_handler_error_that_isnt_a_reset_fails_the_test_when_the_fake_stops() -> None:
    # A handler that died used to pass for one that saw nothing (#301): stop() now names it.
    broken = Line("not bytes")  # type: ignore[arg-type]  # writing it raises TypeError
    fake = FakeOllama([Answer([broken])]).start()
    try:
        # Read to the end: the fake closes the connection only after its error handling has run.
        with contextlib.suppress(http.client.HTTPException, OSError):
            _post(fake.url, "/api/chat", {}).read()
    finally:
        with pytest.raises(AssertionError, match="handler failed: TypeError"):
            fake.stop()


def test_a_client_resetting_its_connection_leaves_the_fakes_stop_quiet() -> None:
    fake = FakeOllama().start()
    handled: list[BaseException | None] = []
    seen = threading.Event()
    original = fake._server.handle_error

    def noting(request: Any, client_address: Any) -> None:  # noqa: ANN401
        handled.append(sys.exc_info()[1])
        original(request, client_address)
        seen.set()

    fake._server.handle_error = noting  # type: ignore[method-assign]
    try:
        host, port = fake.url.removeprefix("http://").split(":")
        client = socket.create_connection((host, int(port)), timeout=10)
        client.sendall(b"POST /api/chat HTTP/1.1\r\nHost: fake\r\nContent-Length: 100\r\n\r\n{")
        # Closing with a zero linger resets the connection while the fake reads the body.
        client.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
        client.close()
        assert seen.wait(HANDLER_DONE_WITHIN), "the fake's handler never saw the reset"
        assert all(isinstance(error, ConnectionError) for error in handled), handled
    finally:
        fake.stop()  # quiet: a reset is a client the fake was told to expect
