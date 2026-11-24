"""Reading a streamed Responses API response into one reply (spec: openai-runner, "A broken stream
is retried as a network failure", "A completed reply without tool calls ends the run"; design D4,
D15). Tested on two recorded runs: OpenAI's gpt-6-luna and local Ollama's qwen3.5:4b.

Its tests that start a process, open a socket or use a git theatre are in
integration/test_openai_stream_integration.py."""

import json
from pathlib import Path
from typing import Any

import pytest

from fake_endpoint import (
    Cut,
    event,
    final,
    function_call,
    message,
    refusal,
    sse,
    usage,
)
from openai_stream_shared import OLLAMA, OPENAI, _read
from troupe_runner_openai.failures import UnreadableError
from troupe_runner_openai.stream import Reply as Parsed
from troupe_runner_openai.stream import ShapeError, StreamError


def _parse(lines: list[Any]) -> Parsed:
    """The reply the stream of ``lines`` reads as, each line ended with a newline, up to any
    Cut."""
    taken: list[str] = []
    for line in lines:
        if isinstance(line, Cut):
            break
        taken.append(line)
    return _read("".join(f"{line}\n" for line in taken).encode("utf-8"))


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


def test_a_last_event_without_its_blank_line_is_cut_short() -> None:
    """The library dispatches an event only on its blank line (openai-library design D5): before
    it, such an event was read."""
    with pytest.raises(StreamError, match="before the service finished"):
        _parse([f"data: {json.dumps(final([message('ok')]))}"])


def test_a_stream_cut_before_its_final_event_is_broken() -> None:
    started = event("response.output_item.added", item=function_call("c1", "Write", "{"))
    with pytest.raises(StreamError, match="before the service finished"):
        _parse([*sse([started]), Cut()])


def _args_as_object() -> dict[str, Any]:
    """A final event whose function_call's arguments are a JSON object rather than its text."""
    done = final([function_call("c1", "Write", "{}")])
    done["response"]["output"][0]["arguments"] = {"file_path": "a.txt"}
    return done


@pytest.mark.parametrize(
    ("data", "words"),
    [
        ("[1, 2]", "has no type"),
        ('{"type": "response.completed", "response": "x"}', "response isn't an object"),
        (
            '{"type": "response.completed", "response": {"status": "completed", "output": 3}}',
            "output isn't a list",
        ),
        (
            json.dumps(_args_as_object()),
            "tool call's arguments is an object, not text",
        ),
    ],
)
def test_a_finished_event_that_cant_be_read_is_the_wrong_shape_not_a_cut(
    data: str, words: str
) -> None:
    with pytest.raises(ShapeError, match=words):
        _parse([f"data: {data}", ""])


def test_a_finished_event_that_isnt_json_is_unreadable_quoting_its_start() -> None:
    with pytest.raises(UnreadableError, match=r"isn't JSON: 'not json'"):
        _parse(["data: not json", ""])


def test_a_final_events_usage_is_kept_when_its_output_cant_be_read() -> None:
    done = final([message("hi")], used=usage(200, 20))
    done["response"]["output"] = 3
    with pytest.raises(ShapeError, match="output isn't a list") as raised:
        _parse([f"data: {json.dumps(done)}", ""])
    assert raised.value.usage is not None
    assert (raised.value.usage["input_tokens"], raised.value.usage["output_tokens"]) == (200, 20)


def test_a_final_events_usage_that_cant_be_read_is_none() -> None:
    done = final([message("hi")], used=usage(200, 20))
    done["response"]["usage"] = 3
    with pytest.raises(ShapeError, match="usage isn't an object") as raised:
        _parse([f"data: {json.dumps(done)}", ""])
    assert raised.value.usage is None


def test_an_event_the_body_ended_inside_is_cut_short() -> None:
    data = json.dumps(final([message("hi")]))
    with pytest.raises(StreamError, match="before the service finished"):
        _parse([f"data: {data[: len(data) // 2]}"])


def test_a_whole_event_the_body_ended_before_its_blank_line_is_cut_short() -> None:
    """Before the library, such an event was finished and read as the wrong shape (design D5)."""
    with pytest.raises(StreamError, match="before the service finished"):
        _parse(['data: {"no": "type"}'])


# Wherever a stream is cut


def _cuts(text: bytes) -> list[int]:
    """Where to cut ``text``: on each side of every line ending and blank line, and every 97th
    byte between, which reaches every kind of cut without reading the stream once per byte."""
    points = {0, len(text)}
    for at, byte in enumerate(text):
        if byte == ord("\n"):
            points.update({at - 1, at, at + 1, at + 2})
    points.update(range(0, len(text), 97))
    return sorted(p for p in points if 0 <= p <= len(text))


def _outcome(data: bytes) -> Parsed | Exception:
    """The reply, or whatever exception reading it raised, so a caller can check its exact type."""
    try:
        return _read(data)
    except Exception as error:
        return error


@pytest.mark.parametrize("which", [OPENAI, OLLAMA], ids=["openai", "ollama"])
def test_a_recorded_stream_cut_anywhere_reads_whole_or_is_cut_short_never_anything_else(
    which: Path,
) -> None:
    """The guard on openai-wrong-shape-ends-run's non-goal (design D6): a stream cut short is
    still retried, however it's cut. Each cut either reads the same reply as the whole stream or
    raises StreamError, the retried error, and never anything else. Through the library, only a
    cut after the final event's blank line reads whole (openai-library design D5)."""
    text = (which / "stream-1.txt").read_bytes()
    whole = _read(text)
    cut_short = 0
    for at in _cuts(text):
        outcome = _outcome(text[:at])
        if isinstance(outcome, Exception):
            assert type(outcome) is StreamError, f"cut at {at}: {outcome!r}"
            cut_short += 1
        else:
            assert outcome == whole, f"cut at {at}"
            assert text[:at].endswith(b"\n\n"), f"cut at {at} read whole before its blank line"
    assert cut_short > 0
