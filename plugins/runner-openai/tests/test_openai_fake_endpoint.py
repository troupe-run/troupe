"""The fake endpoint does what the runner's tests script it to, seen from a plain urllib client
(openai-style-runner design D13). The runner's own tests rely on each behaviour here."""

import json
import math
import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager

import pytest

import fake_endpoint
from fake_endpoint import (
    Cut,
    FakeEndpoint,
    Hold,
    Pause,
    Reply,
    error_reply,
    sse,
    text_reply,
    tool_reply,
)


def _post(endpoint: str, body: bytes = b"{}", headers: dict[str, str] | None = None) -> bytes:
    request = urllib.request.Request(  # noqa: S310 - the fake's own http URL
        endpoint + "/responses", data=body, headers=headers or {}, method="POST"
    )
    with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310
        data: bytes = response.read()
        return data


def test_each_request_is_recorded_with_its_headers_and_body() -> None:
    with FakeEndpoint([text_reply("hi")]) as fake:
        _post(fake.endpoint, b'{"model": "m"}', {"Authorization": "Bearer k"})
        (request,) = fake.requests
    assert (request.method, request.path) == ("POST", "/v1/responses")
    assert request.headers["authorization"] == "Bearer k"
    assert request.json() == {"model": "m"}


def test_waiting_for_requests_ends_when_the_nth_arrives_and_is_false_when_none_does() -> None:
    with FakeEndpoint([Reply(), Reply()]) as fake:
        assert not fake.wait_for_requests(1, 0.1), "no request was made"
        poster = threading.Thread(target=lambda: [_post(fake.endpoint) for _ in range(2)])
        poster.start()
        assert fake.wait_for_requests(2, 30)
        poster.join(30)
        assert len(fake.requests) == 2
        assert not fake.wait_for_requests(3, 0.1)


def test_a_streamed_reply_is_responses_events_ending_in_the_final_one_with_no_done() -> None:
    with FakeEndpoint([text_reply("hello")]) as fake:
        lines = _post(fake.endpoint).decode().splitlines()
    named = [line.removeprefix("event: ") for line in lines if line.startswith("event: ")]
    data = [json.loads(line[6:]) for line in lines if line.startswith("data: ")]
    assert named == [d["type"] for d in data]
    assert named[-1] == "response.completed"
    assert not any("[DONE]" in line for line in lines)
    assert data[-1]["response"]["output"][0]["content"][0]["text"] == "hello"


def test_a_tool_reply_streams_each_calls_arguments_as_two_deltas_and_ends_with_the_call() -> None:
    with FakeEndpoint([tool_reply([("call_1", "Read", {"file_path": "a.txt"})])]) as fake:
        lines = _post(fake.endpoint).decode().splitlines()
    data = [json.loads(line[6:]) for line in lines if line.startswith("data: ")]
    parts = [d["delta"] for d in data if d["type"] == "response.function_call_arguments.delta"]
    assert json.loads("".join(parts)) == {"file_path": "a.txt"}
    assert len(parts) == 2
    (call,) = data[-1]["response"]["output"]
    assert (call["type"], call["call_id"], call["name"]) == ("function_call", "call_1", "Read")


def test_an_error_reply_has_its_status_and_openais_error_shape() -> None:
    reply = error_reply(401, "bad key", headers=[("x-request-id", "r1")])
    with FakeEndpoint([reply]) as fake, pytest.raises(urllib.error.HTTPError) as raised:
        _post(fake.endpoint)
    assert raised.value.code == 401
    assert raised.value.headers["x-request-id"] == "r1"
    assert json.loads(raised.value.read())["error"]["message"] == "bad key"


def test_a_pause_delays_the_rest_of_the_stream() -> None:
    with FakeEndpoint([Reply(lines=sse([Pause(0.3)]))]) as fake:
        started = time.monotonic()
        _post(fake.endpoint)
    assert time.monotonic() - started >= 0.3


CLOSE_SEEN_WITHIN = 5.0
"""Seconds for the fake to see a client close a held reply: room for a loaded machine."""
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


WINDOWS_312_TICK = 0.015625
"""time.monotonic's resolution on Windows with Python 3.12 (GetTickCount64), where #352 failed."""


def test_a_pause_lasts_its_length_by_a_monotonic_clock_as_coarse_as_windows_on_3_12(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A 0.3 s sleep read by a clock that ticks every 15.625 ms comes out as 19 ticks (0.297 s) for
    # most start times: the failure #352 saw. The fake's pause must last its length by that clock.
    real = time.monotonic
    monkeypatch.setattr(
        time, "monotonic", lambda: math.floor(real() / WINDOWS_312_TICK) * WINDOWS_312_TICK
    )
    for _ in range(5):  # different start times within a tick
        started = time.monotonic()
        fake_endpoint.pause(0.3)  # timed alone: the HTTP around it would hide a short pause
        assert time.monotonic() - started >= 0.3


def test_a_pause_in_a_stream_is_the_pause_timed_above(monkeypatch: pytest.MonkeyPatch) -> None:
    # The test above times pause() on its own; this one checks the fake's stream uses it for a
    # Pause, so a stream can't go back to a bare sleep unnoticed (#352).
    paused: list[float] = []
    monkeypatch.setattr(fake_endpoint, "pause", paused.append)
    with FakeEndpoint([Reply(lines=sse([Pause(0.3)]))]) as fake:
        _post(fake.endpoint)
    assert paused == [0.3]


def test_a_cut_ends_the_stream_without_done() -> None:
    with FakeEndpoint([Reply(lines=["data: {}", "", Cut(), "data: [DONE]"])]) as fake:
        request = urllib.request.Request(fake.endpoint + "/responses", data=b"{}")  # noqa: S310
        with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310
            received = b""
            try:
                while chunk := response.read1(65536):
                    received += chunk
            except (OSError, ValueError):
                pass
    assert b"[DONE]" not in received
    assert received.startswith(b"data: {}")


def test_a_held_reply_sees_the_client_close_its_connection() -> None:
    _a_held_reply_sees_the_client_close()


@pytest.mark.skipif(sys.platform == "win32", reason="Windows has no descriptor-number limit")
def test_a_held_reply_sees_the_client_close_on_a_descriptor_past_fd_setsize() -> None:
    with descriptors_past_fd_setsize():
        _a_held_reply_sees_the_client_close()


def _a_held_reply_sees_the_client_close() -> None:
    with FakeEndpoint([Reply(lines=["data: {}", "", Hold()])]) as fake:
        request = urllib.request.Request(fake.endpoint + "/responses", data=b"{}")  # noqa: S310
        response = urllib.request.urlopen(request, timeout=10)  # noqa: S310
        response.readline()

        def close() -> None:
            time.sleep(0.2)
            sock = response.fp.raw._sock
            sock.shutdown(socket.SHUT_RDWR)
            response.close()

        threading.Thread(target=close).start()
        assert fake.wait_for_client_to_close(CLOSE_SEEN_WITHIN)


def test_a_fake_with_no_reply_left_answers_500() -> None:
    with FakeEndpoint() as fake, pytest.raises(urllib.error.HTTPError) as raised:
        _post(fake.endpoint)
    assert raised.value.code == 500
