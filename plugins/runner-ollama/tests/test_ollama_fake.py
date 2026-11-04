"""The fake Ollama plays what it's scripted to, so the runner's tests can trust it
(local-model-runner design D12). Driven with plain http.client, not the runner's client."""

import http.client
import json
import socket
import time

from fake_ollama import Answer, Line, Settings, done, final, message, serving


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
