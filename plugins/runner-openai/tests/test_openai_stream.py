"""Reading a streamed Responses API response into one reply (spec: openai-runner, "A broken stream
is retried as a network failure", "A completed reply without tool calls ends the run"; design D4,
D15). Tested on two recorded runs: OpenAI's gpt-6-luna and local Ollama's qwen3.5:4b."""

import json
from pathlib import Path
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from fake_endpoint import (
    Cut,
    FakeEndpoint,
    Reply,
    event,
    final,
    function_call,
    message,
    refusal,
    sse,
    usage,
)
from troupe_runner_openai.service import Call, parse_endpoint
from troupe_runner_openai.stream import Reply as Parsed
from troupe_runner_openai.stream import StreamError, StreamParser

DATA = Path(__file__).parent / "data"
OPENAI = DATA / "openai-responses-loop"
OLLAMA = DATA / "ollama-responses-loop"


def _parse(lines: list[Any]) -> Parsed:
    parser = StreamParser()
    for line in lines:
        if isinstance(line, Cut):
            break
        if parser.feed(line):
            break
    return parser.reply()


def _recorded(directory: Path, n: int) -> Parsed:
    return _parse((directory / f"stream-{n}.txt").read_text(encoding="utf-8").splitlines())


# The recordings


def test_openais_first_response_is_one_read_call_with_usage() -> None:
    reply = _recorded(OPENAI, 1)
    assert reply.status == "completed"
    assert [(c.call_id, c.name, json.loads(c.arguments)) for c in reply.tool_calls] == [
        ("call_NPKm1VnAslnyZfbP0a5BAqMq", "Read", {"file_path": "notes/todo.txt"})
    ]
    assert reply.text == ""
    assert reply.usage is not None
    assert (reply.usage["input_tokens"], reply.usage["output_tokens"]) == (75, 21)
    assert reply.usage["input_tokens_details"] == {"cache_write_tokens": 0, "cached_tokens": 0}
    assert reply.model == "gpt-6-luna"


def test_openais_second_response_completes_with_its_message() -> None:
    reply = _recorded(OPENAI, 2)
    assert (reply.status, reply.text, reply.tool_calls) == (
        "completed",
        "Buy milk and write the troupe docs.",
        [],
    )


def test_ollamas_first_response_is_reasoning_then_a_read_call() -> None:
    reply = _recorded(OLLAMA, 1)
    assert [item["type"] for item in reply.output] == ["reasoning", "function_call"]
    assert [c.name for c in reply.tool_calls] == ["Read"]
    assert json.loads(reply.tool_calls[0].arguments) == {"file_path": "notes/todo.txt"}
    assert reply.model == "qwen3.5:4b"


def test_ollamas_second_response_completes_after_reasoning() -> None:
    reply = _recorded(OLLAMA, 2)
    assert reply.status == "completed"
    assert [item["type"] for item in reply.output] == ["reasoning", "message"]
    assert reply.text
    assert reply.usage is not None
    assert reply.usage["input_tokens_details"]["cached_tokens"] == 373


def test_the_output_items_are_kept_unchanged_to_send_back() -> None:
    lines = (OLLAMA / "stream-1.txt").read_text(encoding="utf-8").splitlines()
    completed = next(json.loads(line[6:]) for line in lines if '"response.completed"' in line)
    assert _recorded(OLLAMA, 1).output == completed["response"]["output"]


def test_the_recorded_second_request_sent_back_the_first_responses_output() -> None:
    sent = json.loads((OPENAI / "request-2.json").read_text(encoding="utf-8"))["input"]
    first = _recorded(OPENAI, 1).output
    assert sent[1 : 1 + len(first)] == first
    assert sent[-1]["type"] == "function_call_output"


# Shapes the recordings don't hold


def test_the_response_objects_own_status_wins_over_its_events_name() -> None:
    odd = final([message("hm")])
    odd["response"]["status"] = "paused"
    assert _parse(sse([odd])).status == "paused"


def test_the_events_name_gives_the_status_when_the_object_has_none() -> None:
    bare = final([message("ok")])
    del bare["response"]["status"]
    assert _parse(sse([bare])).status == "completed"


def test_a_refusal_is_read_apart_from_the_text() -> None:
    reply = _parse(sse([final([refusal("I can't help with that.")])]))
    assert (reply.text, reply.refusal) == ("", "I can't help with that.")


def test_an_incomplete_response_says_why() -> None:
    reply = _parse(sse([final([message("partial")], "incomplete", incomplete="max_output_tokens")]))
    assert (reply.status, reply.incomplete_reason, reply.text) == (
        "incomplete",
        "max_output_tokens",
        "partial",
    )


def test_a_failed_response_carries_its_error() -> None:
    failed = final([], "failed", error={"code": "server_error", "message": "boom"})
    reply = _parse(sse([failed]))
    assert reply.status == "failed"
    assert reply.failure is not None
    assert (reply.failure.code, reply.failure.message) == ("server_error", "boom")


def test_an_error_event_ends_the_stream_with_its_code() -> None:
    reply = _parse(sse([event("error", code="rate_limit_exceeded", message="slow down")]))
    assert reply.status == "error"
    assert reply.failure is not None
    assert reply.failure.code == "rate_limit_exceeded"


def test_a_call_without_a_call_id_is_read_with_none() -> None:
    reply = _parse(sse([final([function_call(None, "Read", {"file_path": "a"})])]))
    assert reply.tool_calls[0].call_id is None


def test_comments_and_event_lines_are_read_past() -> None:
    data = json.dumps(final([message("this")], used=usage(1, 1)))
    assert _parse([": keep-alive", "event: response.completed", f"data: {data}", ""]).text == "this"


def test_a_last_event_without_its_blank_line_is_still_read() -> None:
    assert _parse([f"data: {json.dumps(final([message('ok')]))}"]).text == "ok"


def test_a_stream_cut_before_its_final_event_is_broken() -> None:
    started = event("response.output_item.added", item=function_call("c1", "Write", "{"))
    with pytest.raises(StreamError, match="before the service finished"):
        _parse([*sse([started]), Cut()])


@pytest.mark.parametrize(
    ("data", "words"),
    [
        ("not json", "isn't JSON"),
        ("[1, 2]", "has no type"),
        ('{"type": "response.completed", "response": "x"}', "response isn't an object"),
        (
            '{"type": "response.completed", "response": {"status": "completed", "output": 3}}',
            "output",
        ),
    ],
)
def test_an_event_that_cant_be_read_breaks_the_stream(data: str, words: str) -> None:
    with pytest.raises(StreamError, match=words):
        _parse([f"data: {data}", ""])


# However the bytes arrive


def _through_the_service(fake: FakeEndpoint) -> Parsed:
    call = Call(parse_endpoint(fake.endpoint), b"{}", None)
    parser = StreamParser()
    for line in call.open().lines():
        if parser.feed(line):
            break
    return parser.reply()


@settings(max_examples=25, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    cuts=st.lists(st.integers(min_value=0), max_size=12), which=st.sampled_from([OPENAI, OLLAMA])
)
def test_however_a_recorded_streams_bytes_are_split_into_reads_the_reply_is_the_same(
    cuts: list[int], which: Path
) -> None:
    data = (which / "stream-1.txt").read_bytes()
    points = sorted({c % (len(data) + 1) for c in cuts})
    pieces = [data[a:b] for a, b in zip([0, *points], [*points, len(data)], strict=True)]
    with FakeEndpoint([Reply(chunks=[p for p in pieces if p])]) as fake:
        reply = _through_the_service(fake)
    assert reply == _parse(data.decode("utf-8").splitlines())
