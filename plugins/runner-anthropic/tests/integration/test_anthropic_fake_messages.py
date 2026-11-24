"""The fake Messages API serves what the runner's tests script, read by the real anthropic library
(anthropic-runner design D14). The runner's other tests rely on each behaviour here."""

import threading
import time
from typing import Any

import anthropic
import pytest

from fake_messages import (
    FakeEndpoint,
    Gate,
    Reply,
    error_reply,
    stream_error_reply,
    text_reply,
    tool_reply,
)

PARAMS: dict[str, Any] = {
    "model": "m",
    "max_tokens": 5,
    "messages": [{"role": "user", "content": "hi"}],
}


def _stream(endpoint: str) -> Any:  # noqa: ANN401 - the library's Stream
    """The library's own client, asking ``endpoint`` for a streamed reply as the runner does."""
    client = anthropic.Anthropic(base_url=endpoint, api_key="x", max_retries=0)
    return client.messages.create(**PARAMS, stream=True)


def _events(endpoint: str) -> list[dict[str, Any]]:
    return [event.to_dict(mode="json") for event in _stream(endpoint)]


def test_a_text_reply_is_read_by_the_library_as_one_whole_message_and_the_request_is_recorded() -> (
    None
):
    with FakeEndpoint([text_reply("Hello there.", prompt=12, completion=3)]) as fake:
        events = _events(fake.endpoint)
        (request,) = fake.requests
    assert [e["type"] for e in events] == [
        "message_start",
        "content_block_start",
        "content_block_delta",
        "content_block_delta",
        "content_block_stop",
        "message_delta",
        "message_stop",
    ]
    text = "".join(e["delta"]["text"] for e in events if e["type"] == "content_block_delta")
    assert text == "Hello there."
    assert events[0]["message"]["usage"]["input_tokens"] == 12
    assert events[-2]["delta"]["stop_reason"] == "end_turn"
    assert events[-2]["usage"]["output_tokens"] == 3
    assert (request.method, request.path) == ("POST", "/v1/messages")
    assert request.headers["authorization"] == "Bearer x"
    assert request.json() == {**PARAMS, "stream": True}


def test_a_tool_reply_streams_its_input_as_two_json_deltas_the_library_passes_through() -> None:
    with FakeEndpoint([tool_reply([("toolu_1", "Read", {"file_path": "a.txt"})])]) as fake:
        events = _events(fake.endpoint)
    (started,) = [e for e in events if e["type"] == "content_block_start"]
    block = started["content_block"]
    assert (block["type"], block["id"], block["name"]) == ("tool_use", "toolu_1", "Read")
    parts = [e["delta"]["partial_json"] for e in events if e["type"] == "content_block_delta"]
    assert len(parts) == 2
    assert "".join(parts) == '{"file_path": "a.txt"}'
    assert events[-2]["delta"]["stop_reason"] == "tool_use"


def test_an_error_reply_is_the_librarys_status_error_with_the_apis_error_shape() -> None:
    with (
        FakeEndpoint([error_reply(401, "bad key", "authentication_error")]) as fake,
        pytest.raises(anthropic.AuthenticationError) as raised,
    ):
        _stream(fake.endpoint)
    assert raised.value.status_code == 401
    assert raised.value.body == {
        "type": "error",
        "error": {"type": "authentication_error", "message": "bad key"},
    }


def test_a_stream_error_event_is_raised_by_the_library_while_reading_the_stream() -> None:
    with FakeEndpoint([stream_error_reply("overloaded_error", "Overloaded")]) as fake:
        stream = _stream(fake.endpoint)
        with pytest.raises(anthropic.APIStatusError) as raised:
            list(stream)
    assert raised.value.body == {
        "type": "error",
        "error": {"type": "overloaded_error", "message": "Overloaded"},
    }


def test_a_gate_holds_the_rest_of_the_stream_until_it_is_opened() -> None:
    opened = threading.Event()
    with FakeEndpoint([text_reply("late", gate=Gate(opened))]) as fake:
        stream = _stream(fake.endpoint)
        assert next(iter(stream)).type == "message_start"
        assert not opened.is_set()
        opened.set()
        rest = [event.type for event in stream]
    assert rest[-1] == "message_stop"


def test_a_reply_left_out_of_the_script_is_a_500_naming_that() -> None:
    with (
        FakeEndpoint([]) as fake,
        pytest.raises(anthropic.InternalServerError, match="no reply left"),
    ):
        _stream(fake.endpoint)


def test_a_body_given_with_status_200_is_sent_as_application_json() -> None:
    with FakeEndpoint([Reply(200, body=b'{"id": "msg_1"}')]) as fake:
        client = anthropic.Anthropic(base_url=fake.endpoint, api_key="x", max_retries=0)
        response = client.messages.with_raw_response.create(**PARAMS)
    assert response.headers["content-type"] == "application/json"


def _handlers() -> list[threading.Thread]:
    return [t for t in threading.enumerate() if "process_request_thread" in t.name]


def test_no_handler_thread_outlives_an_error_reply_to_a_pooled_client() -> None:
    # A kept-alive connection held a handler thread open past its test, and another suite in the
    # same worker waits for every thread named process_request_thread to end (the Claude Code
    # runner's capture tests): the fake closes each connection after its reply.
    client = anthropic.Anthropic(base_url="http://127.0.0.1:1", api_key="x", max_retries=0)
    with FakeEndpoint([error_reply(429, "slow down", "rate_limit_error")]) as fake:
        client = client.with_options(base_url=fake.endpoint)
        with pytest.raises(anthropic.RateLimitError):
            client.messages.create(**PARAMS, stream=True)
        deadline = time.monotonic() + 5
        while _handlers() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert _handlers() == []
