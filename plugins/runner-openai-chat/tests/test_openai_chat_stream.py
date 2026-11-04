"""Reading a streamed response into one reply (spec: openai-chat-runner, "A broken stream is
retried as a network failure", "Assistant text is reported as turns"; design D4)."""

import json
from pathlib import Path
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from fake_endpoint import Cut, FakeEndpoint, Reply, chunk, sse, usage
from troupe_runner_openai_chat.service import Call, parse_endpoint
from troupe_runner_openai_chat.stream import Reply as Parsed
from troupe_runner_openai_chat.stream import StreamError, StreamParser

RECORDED = Path(__file__).parent / "data" / "ollama-read-stream" / "stream.txt"


def _parse(lines: list[Any]) -> Parsed:
    parser = StreamParser()
    for line in lines:
        if isinstance(line, Cut):
            break
        if parser.feed(line):
            break
    return parser.reply()


def test_text_split_over_chunks_is_one_reply_with_its_finish_usage_and_model() -> None:
    reply = _parse(
        sse(
            [
                chunk({"role": "assistant", "content": ""}, model="gpt-x-2026-01-01"),
                chunk({"content": "Wrote "}),
                chunk({"content": "out/hello.txt."}),
                chunk(finish="stop"),
                chunk(usage=usage(100, 10, cached=40)),
            ]
        )
    )
    assert reply.text == "Wrote out/hello.txt."
    assert reply.finish == "stop"
    assert reply.tool_calls == []
    assert reply.usage == usage(100, 10, cached=40)
    assert reply.model == "fake-model"


def test_tool_calls_are_built_by_index_from_their_deltas() -> None:
    lines = sse(
        [
            chunk({"tool_calls": [{"index": 0, "id": "c1", "function": {"name": "Read"}}]}),
            chunk({"tool_calls": [{"index": 1, "id": "c2", "function": {"name": "Glob"}}]}),
            chunk({"tool_calls": [{"index": 0, "function": {"arguments": '{"file_'}}]}),
            chunk({"tool_calls": [{"index": 1, "function": {"arguments": '{"pattern": "*"}'}}]}),
            chunk({"tool_calls": [{"index": 0, "function": {"arguments": 'path": "a"}'}}]}),
            chunk(finish="tool_calls"),
        ]
    )
    reply = _parse(lines)
    assert [(c.id, c.name, json.loads(c.arguments)) for c in reply.tool_calls] == [
        ("c1", "Read", {"file_path": "a"}),
        ("c2", "Glob", {"pattern": "*"}),
    ]


def test_a_tool_call_without_an_id_keeps_none_for_the_runner_to_fill() -> None:
    lines = sse(
        [
            chunk({"tool_calls": [{"index": 0, "function": {"name": "Read"}}]}),
            chunk(finish="tool_calls"),
        ]
    )
    assert _parse(lines).tool_calls[0].id is None


def test_a_refusal_and_reasoning_are_kept_apart_from_the_text() -> None:
    lines = sse(
        [
            chunk({"reasoning_content": "thinking"}),
            chunk({"refusal": "I can't "}),
            chunk({"refusal": "help with that."}),
            chunk(finish="stop"),
        ]
    )
    reply = _parse(lines)
    assert (reply.text, reply.refusal, reply.reasoning) == (
        "",
        "I can't help with that.",
        "thinking",
    )


def test_other_choices_comments_and_other_fields_are_ignored() -> None:
    data = chunk({"content": "this"}, finish="stop")
    data["choices"].insert(0, {"index": 1, "delta": {"content": "not this"}, "finish_reason": None})
    lines = [": keep-alive", "event: message", f"data: {json.dumps(data)}", "", "data: [DONE]"]
    assert _parse(lines).text == "this"


def test_a_body_that_ends_after_the_finish_without_done_is_complete() -> None:
    lines = sse([chunk({"content": "ok"}), chunk(finish="stop")], done=False)
    assert _parse(lines).finish == "stop"


def test_a_last_event_without_its_blank_line_is_still_read() -> None:
    lines = [f"data: {json.dumps(chunk({'content': 'ok'}, finish='stop'))}"]
    assert _parse(lines).text == "ok"


def test_a_stream_cut_before_its_finish_is_broken_and_its_calls_are_dropped() -> None:
    start = chunk(
        {
            "tool_calls": [
                {"index": 0, "id": "c1", "function": {"name": "Write", "arguments": '{"fi'}}
            ]
        }
    )
    with pytest.raises(StreamError, match="before the model finished"):
        _parse([*sse([start], done=False), Cut()])


@pytest.mark.parametrize(
    ("data", "words"),
    [
        ("not json", "isn't JSON"),
        ("[1, 2]", "isn't a JSON object"),
        ('{"choices": "x"}', "choices aren't a list"),
        ('{"choices": [{"index": 0, "delta": {"content": 5}}]}', "content is int"),
        ('{"choices": [{"index": 0, "delta": {"tool_calls": [{"index": -1}]}}]}', "index"),
        ('{"error": {"message": "overloaded"}}', "overloaded"),
    ],
)
def test_an_event_that_isnt_a_chunk_breaks_the_stream(data: str, words: str) -> None:
    with pytest.raises(StreamError, match=words):
        _parse([f"data: {data}", ""])


def _split(text: str, cuts: list[int]) -> list[str]:
    points = sorted({c % (len(text) + 1) for c in cuts})
    return [text[a:b] for a, b in zip([0, *points], [*points, len(text)], strict=True)]


@given(
    text=st.text(max_size=80),
    arguments=st.dictionaries(st.text(max_size=8), st.text(max_size=8), max_size=4),
    text_cuts=st.lists(st.integers(min_value=0), max_size=6),
    argument_cuts=st.lists(st.integers(min_value=0), max_size=6),
)
def test_however_the_service_splits_text_and_arguments_the_reply_is_the_same(
    text: str,
    arguments: dict[str, str],
    text_cuts: list[int],
    argument_cuts: list[int],
) -> None:
    raw = json.dumps(arguments)
    chunks: list[Any] = [chunk({"content": part}) for part in _split(text, text_cuts)]
    head = {"index": 0, "id": "c1", "function": {"name": "Write"}}
    chunks.append(chunk({"tool_calls": [head]}))
    chunks += [
        chunk({"tool_calls": [{"index": 0, "function": {"arguments": part}}]})
        for part in _split(raw, argument_cuts)
    ]
    chunks.append(chunk(finish="tool_calls"))
    reply = _parse(sse(chunks))
    assert reply.text == text
    assert json.loads(reply.tool_calls[0].arguments) == arguments


# A recorded stream (data/ollama-read-stream: Ollama 0.40.14, qwen3.5:4b)


def test_a_recorded_ollama_stream_is_a_read_call_with_reasoning_and_usage() -> None:
    reply = _parse(RECORDED.read_text(encoding="utf-8").splitlines())
    assert reply.finish == "tool_calls"
    assert reply.text == ""
    assert reply.reasoning.startswith("The user wants me to read")
    (call,) = reply.tool_calls
    assert (call.id, call.name, json.loads(call.arguments)) == (
        "call_fqvwfbay",
        "Read",
        {"file_path": "notes/todo.txt"},
    )
    assert reply.usage is not None
    assert (reply.usage["prompt_tokens"], reply.usage["completion_tokens"]) == (1071, 76)
    assert reply.model == "qwen3.5:4b"


def _through_the_service(fake: FakeEndpoint) -> Parsed:
    call = Call(parse_endpoint(fake.endpoint), b"{}", None)
    parser = StreamParser()
    for line in call.open().lines():
        if parser.feed(line):
            break
    return parser.reply()


@settings(max_examples=25, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(cuts=st.lists(st.integers(min_value=0), max_size=12))
def test_however_the_recorded_streams_bytes_are_split_into_reads_the_reply_is_the_same(
    cuts: list[int],
) -> None:
    data = RECORDED.read_bytes()
    points = sorted({c % (len(data) + 1) for c in cuts})
    pieces = [data[a:b] for a, b in zip([0, *points], [*points, len(data)], strict=True)]
    with FakeEndpoint([Reply(chunks=[p for p in pieces if p])]) as fake:
        reply = _through_the_service(fake)
    assert reply == _parse(data.decode("utf-8").splitlines())
