"""The capture tool's stand-in Messages API, over a local socket: the compaction stand-in answers a
read, then the summary, then done, counting one compaction, and the reactive stand-in refuses the
second ordinary request and counts the refusal (spec: claude-code-runner; compaction-off design
D3; compaction-opt-in design D10).

Its tests that stay in their own process are in unit/test_claude_code_capture.py."""

import json
from pathlib import Path
from typing import Any

from claude_code_capture_shared import _tool


def _recording_errors(server: Any) -> list[object]:  # noqa: ANN401 - the tool's server
    """The errors the stand-in hits while handling a request, kept instead of printed."""
    errors: list[object] = []
    server.handle_error = lambda _request, address: errors.append(address)
    return errors


def _all_handled(errors: list[object]) -> None:
    """Every stand-in request thread has ended, and none hit an error. A thread still writing to a
    connection the test closed prints its traceback during a later test, and that reads the tool's
    source there, which the read guard charges to that test (#403's merge queue run)."""
    import threading
    import time

    deadline = time.monotonic() + 5
    while [t for t in threading.enumerate() if "process_request_thread" in t.name]:
        assert time.monotonic() < deadline, "a stand-in request thread is still running"
        time.sleep(0.01)
    assert errors == []


def test_the_compaction_stand_in_answers_read_then_summary_then_done(tmp_path: Path) -> None:
    import http.client

    tool = _tool()
    server, requests, compactions, refusals = tool._compaction_api(
        990_000, tmp_path / "notes.txt", False
    )
    errors = _recording_errors(server)
    port = server.server_address[1]

    def post(text: str) -> bytes:
        body = {"model": "m", "messages": [{"role": "user", "content": text}]}
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        try:
            connection.request("POST", "/v1/messages", json.dumps(body).encode())
            return connection.getresponse().read()
        finally:
            connection.close()

    try:
        first = post("Read notes.txt")
        summary = post("Your task is to create a detailed summary of the conversation so far.")
        last = post("Continue.")
    finally:
        server.shutdown()
        server.server_close()
    _all_handled(errors)
    assert b'"name": "Read"' in first
    assert b'"input_tokens": 990000' in first
    assert json.dumps(tool.SUMMARY)[1:-1].encode() in summary
    assert b'"text": "done"' in last
    assert len(requests) == 3
    assert len(compactions) == 1
    assert refusals == []


def test_the_reactive_stand_in_refuses_the_second_ordinary_request_and_counts_it(
    tmp_path: Path,
) -> None:
    import http.client

    tool = _tool()
    server, _, _, refusals = tool._compaction_api(185_000, tmp_path / "notes.txt", True)
    errors = _recording_errors(server)
    port = server.server_address[1]
    statuses = []
    try:
        for text in ("Read notes.txt", "Continue."):
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
            body = {"model": "m", "messages": [{"role": "user", "content": text}]}
            connection.request("POST", "/v1/messages", json.dumps(body).encode())
            answer = connection.getresponse()
            # Read it all, so the stand-in finishes writing before the connection closes: a
            # handler left writing hits a broken pipe after the test, and its traceback reads
            # the tool's source during whatever test runs then.
            answer.read()
            statuses.append(answer.status)
            connection.close()
    finally:
        server.shutdown()
        server.server_close()
    _all_handled(errors)
    assert statuses == [200, 400]
    assert len(refusals) == 1
