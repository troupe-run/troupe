"""The Ollama client: preflight requests, a streamed answer, failures classified as design D9 says,
and a close from another thread (spec: ollama-runner; local-model-runner design D2, D3, D9)."""

import json
import socket
import threading
import time

import pytest

from fake_ollama import Answer, Line, Settings, done, final, message, serving
from troupe_runner_ollama.client import (
    Client,
    EngineError,
    RetryableError,
    StoppedError,
    UnreachableError,
    error_text,
)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port: int = sock.getsockname()[1]
        return port


# Preflight


def test_version_is_ollamas_version() -> None:
    with serving() as fake:
        assert Client(fake.url).version(5) == "0.12.6"


def test_nothing_listening_is_unreachable() -> None:
    with pytest.raises(UnreachableError):
        Client(f"http://127.0.0.1:{_free_port()}").version(5)


def test_a_version_answer_that_isnt_ollamas_is_unreachable() -> None:
    settings = Settings(version_body=b"<html>hello</html>")
    with serving(settings=settings) as fake, pytest.raises(UnreachableError, match="Ollama's"):
        Client(fake.url).version(5)


def test_a_silent_server_is_unreachable_after_the_timeout() -> None:
    with serving(settings=Settings(silent_preflight=True)) as fake:
        started = time.monotonic()
        with pytest.raises(UnreachableError):
            Client(fake.url).version(0.3)
        assert time.monotonic() - started < 5


def test_show_is_the_models_details_or_none_when_ollama_has_none() -> None:
    with serving() as fake:
        client = Client(fake.url)
        shown = client.show("fake", 5)
        assert shown is not None
        assert "tools" in shown["capabilities"]
        assert client.show("missing", 5) is None


# A streamed answer


def test_chat_yields_each_line_without_its_line_ending_and_sends_the_exact_body() -> None:
    body = b'{"model":"fake","messages":[]}'
    with serving([final("hello")]) as fake:
        lines = list(Client(fake.url).chat(body))
        assert [json.loads(line)["done"] for line in lines] == [False, True]
        assert all(not line.endswith(b"\n") for line in lines)
        assert fake.chat_bodies() == [body]


# Failures (design D9)


@pytest.mark.parametrize("status", [500, 502, 503, 504])
def test_a_server_status_is_a_server_retry_with_its_body(status: int) -> None:
    with serving([Answer(status=status, body=b'{"error":"busy"}')]) as fake:
        with pytest.raises(RetryableError) as caught:
            list(Client(fake.url).chat(b"{}"))
        assert caught.value.reason == "server"
        assert caught.value.body == b'{"error":"busy"}'
        assert "busy" in caught.value.message


@pytest.mark.parametrize("status", [400, 404, 429, 501])
def test_any_other_status_is_an_engine_error_with_ollamas_message(status: int) -> None:
    body = b'{"error":"model failed to load"}'
    with serving([Answer(status=status, body=body)]) as fake:
        with pytest.raises(EngineError) as caught:
            list(Client(fake.url).chat(b"{}"))
        assert caught.value.status == status
        assert caught.value.body == body
        assert "model failed to load" in caught.value.message


def test_a_refused_connection_is_a_network_retry() -> None:
    with pytest.raises(RetryableError) as caught:
        list(Client(f"http://127.0.0.1:{_free_port()}").chat(b"{}"))
    assert caught.value.reason == "network"


def test_a_dropped_connection_ends_the_lines_before_the_answers_done_line() -> None:
    # http.client reads a stream cut short as ended: the conversation, which knows an answer ends
    # with a done line, makes it a network retry.
    with serving([Answer([message("a"), message("b"), done()], close_after=1)]) as fake:
        lines = list(Client(fake.url).chat(b"{}"))
        assert [json.loads(line)["message"]["content"] for line in lines] == ["a"]


def test_a_silent_stream_is_a_network_retry_after_the_idle_timeout() -> None:
    with serving([Answer([message("a")], silent=True)]) as fake:
        with pytest.raises(RetryableError, match=r"sent nothing for 0\.3s") as caught:
            list(Client(fake.url, idle_timeout=0.3).chat(b"{}"))
        assert caught.value.reason == "network"


def test_a_line_over_the_limit_is_a_network_retry_and_never_read_whole() -> None:
    long_line = b'{"x":"' + b"a" * 5000 + b'"}'
    with serving([Answer([long_line, done()])]) as fake:
        with pytest.raises(RetryableError, match="longer than 1024 bytes") as caught:
            list(Client(fake.url, line_max_bytes=1024).chat(b"{}"))
        assert caught.value.reason == "network"


def test_error_text_is_ollamas_message_or_the_status_and_body() -> None:
    assert error_text(b'{"error":"boom"}', 500) == "boom"
    assert error_text(b"bad gateway", 502) == "status 502: bad gateway"
    assert error_text(b"", 503) == "status 503"


# Closing from another thread (design D3)


def test_close_from_another_thread_wakes_a_blocked_read_within_a_second() -> None:
    with serving([Answer([message("a"), Line(b"{}", delay=30)])]) as fake:
        client = Client(fake.url)
        lines = client.chat(b"{}")
        next(lines)
        timer = threading.Timer(0.2, client.close)
        timer.start()
        started = time.monotonic()
        with pytest.raises(StoppedError):
            next(lines)
        assert time.monotonic() - started < 1.2
        assert fake.closed_by_client.wait(5)


def test_a_closed_client_makes_no_further_request() -> None:
    with serving([final("a")]) as fake:
        client = Client(fake.url)
        client.close()
        with pytest.raises(StoppedError):
            list(client.chat(b"{}"))
        assert fake.chats() == []
