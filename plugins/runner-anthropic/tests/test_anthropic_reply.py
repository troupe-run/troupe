"""One reply gathered from its stream events (spec: anthropic-runner, "Tool calls are carried out
in order and answered in the next request", "A malformed tool call is answered, not fatal", "A
reply the runner can't read ends the run", "Usage is summed into the result", "A reply made from a
cut conversation is never acted on"; design D7, D8).

The events are built with fake_messages' builders, the same the fake endpoint streams, and fed to
ReplyParser as dicts, as the library's ``to_dict`` gives them."""

import json
from collections.abc import Iterable
from itertools import pairwise
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from fake_messages import event, finish, start, text_block, thinking_block, tool_block, usage
from troupe_runner_anthropic.reply import Reply, ReplyParser, ShapeError, ToolUse


def _parse(events: Iterable[dict[str, Any]]) -> Reply:
    parser = ReplyParser()
    done = False
    for item in events:
        assert not done, "an event after message_stop"
        done = parser.feed(item)
    assert done, "the events never reached message_stop"
    return parser.reply()


def _feed(events: Iterable[dict[str, Any]]) -> ReplyParser:
    parser = ReplyParser()
    for item in events:
        parser.feed(item)
    return parser


# Text


def test_text_blocks_are_joined_with_a_blank_line_and_kept_as_content() -> None:
    reply = _parse(
        [start(), *text_block(0, "First part."), *text_block(1, "Second."), *finish("end_turn")]
    )
    assert reply.text == "First part.\n\nSecond."
    assert reply.content == [
        {"type": "text", "text": "First part."},
        {"type": "text", "text": "Second."},
    ]
    assert reply.stop_reason == "end_turn"
    assert reply.tool_uses == []


def test_an_empty_text_block_adds_no_text_but_stays_in_the_content() -> None:
    reply = _parse([start(), *text_block(0, ""), *text_block(1, "Only."), *finish("end_turn")])
    assert reply.text == "Only."
    assert len(reply.content) == 2


def test_the_replys_model_is_message_starts_and_an_empty_one_is_none() -> None:
    assert _parse([start("google/gemma-4-e4b"), *finish("end_turn")]).model == "google/gemma-4-e4b"
    assert _parse([start(""), *finish("end_turn")]).model is None


# Requirement: Tool calls are carried out in order and answered in the next request,
# "Thinking is sent back as the service gave it"


def test_a_thinking_block_is_kept_with_its_signature_before_the_tool_use() -> None:
    reply = _parse(
        [
            start(),
            *thinking_block(0, "Let me look.", "sig-abc"),
            *tool_block(1, "toolu_1", "Read", {"file_path": "a.txt"}),
            *finish("tool_use"),
        ]
    )
    assert reply.content[0] == {
        "type": "thinking",
        "thinking": "Let me look.",
        "signature": "sig-abc",
    }
    assert reply.content[1]["type"] == "tool_use"
    assert reply.text == ""


def test_a_blocks_fields_the_runner_doesnt_read_are_kept_unchanged() -> None:
    block = {"type": "redacted_thinking", "data": "opaque=="}
    reply = _parse(
        [
            start(),
            event("content_block_start", index=0, content_block=block),
            event("content_block_stop", index=0),
            *finish("end_turn"),
        ]
    )
    assert reply.content == [block]


def test_blocks_are_ordered_by_index_not_by_arrival() -> None:
    reply = _parse(
        [start(), *text_block(1, "second"), *text_block(0, "first"), *finish("end_turn")]
    )
    assert reply.text == "first\n\nsecond"


# Tool calls


def test_tool_use_input_is_joined_across_deltas_and_parsed() -> None:
    arguments = {"file_path": "out/hello.txt", "content": 'héllo, "world"\n'}
    reply = _parse([start(), *tool_block(0, "toolu_1", "Write", arguments), *finish("tool_use")])
    assert reply.tool_uses == [ToolUse("toolu_1", "Write", arguments)]
    assert reply.content == [
        {"type": "tool_use", "id": "toolu_1", "name": "Write", "input": arguments}
    ]


@given(
    arguments=st.dictionaries(
        st.text(max_size=8),
        st.recursive(
            st.none() | st.booleans() | st.integers() | st.text(max_size=8),
            lambda inner: (
                st.lists(inner, max_size=3)
                | st.dictionaries(st.text(max_size=4), inner, max_size=3)
            ),
            max_leaves=6,
        ),
        max_size=4,
    ),
    cuts=st.lists(st.integers(min_value=0, max_value=200), max_size=6),
)
def test_tool_use_input_split_anywhere_is_parsed_to_the_object_sent(
    arguments: dict[str, Any], cuts: list[int]
) -> None:
    raw = json.dumps(arguments)
    points = sorted({0, len(raw), *(min(cut, len(raw)) for cut in cuts)})
    deltas = [
        event(
            "content_block_delta",
            index=0,
            delta={"type": "input_json_delta", "partial_json": raw[a:b]},
        )
        for a, b in pairwise(points)
    ]
    reply = _parse(
        [
            start(),
            event(
                "content_block_start",
                index=0,
                content_block={"type": "tool_use", "id": "t", "name": "Read", "input": {}},
            ),
            *deltas,
            event("content_block_stop", index=0),
            *finish("tool_use"),
        ]
    )
    assert reply.tool_uses == [ToolUse("t", "Read", arguments)]


def test_two_tool_uses_are_kept_in_order() -> None:
    reply = _parse(
        [
            start(),
            *tool_block(0, "toolu_a", "Read", {"file_path": "a.txt"}),
            *tool_block(1, "toolu_b", "Read", {"file_path": "b.txt"}),
            *finish("tool_use"),
        ]
    )
    assert [(use.call_id, use.arguments) for use in reply.tool_uses] == [
        ("toolu_a", {"file_path": "a.txt"}),
        ("toolu_b", {"file_path": "b.txt"}),
    ]


def test_a_tool_use_with_no_input_deltas_keeps_the_input_it_started_with() -> None:
    reply = _parse(
        [
            start(),
            event(
                "content_block_start",
                index=0,
                content_block={
                    "type": "tool_use",
                    "id": "t",
                    "name": "Glob",
                    "input": {"pattern": "*"},
                },
            ),
            event("content_block_stop", index=0),
            *finish("tool_use"),
        ]
    )
    assert reply.tool_uses == [ToolUse("t", "Glob", {"pattern": "*"})]


# Requirement: A malformed tool call is answered, not fatal, "Input that isn't JSON"


@pytest.mark.parametrize(
    "raw", ['{"file_path": "a.txt"', "[1, 2]", '"text"', "42", "null", "not json"], ids=repr
)
def test_input_that_isnt_a_json_object_is_kept_as_text_and_the_block_sent_back_with_empty_input(
    raw: str,
) -> None:
    reply = _parse([start(), *tool_block(0, "toolu_1", "Write", raw), *finish("tool_use")])
    assert reply.tool_uses == [ToolUse("toolu_1", "Write", raw)]
    assert reply.content == [{"type": "tool_use", "id": "toolu_1", "name": "Write", "input": {}}]


# Requirement: A reply the runner can't read ends the run


@pytest.mark.parametrize(
    ("call_id", "name"), [(None, "Read"), ("", "Read"), ("toolu_1", None), ("toolu_1", "")]
)
def test_a_tool_use_without_an_id_or_a_name_raises_shape_error_with_the_usage(
    call_id: str | None, name: str | None
) -> None:
    events = [start(used=usage(12, 1)), *tool_block(0, call_id, name, {}), *finish("tool_use", 7)]
    parser = _feed(events)
    with pytest.raises(ShapeError) as raised:
        parser.reply()
    assert ("no id" if not call_id else "no name") in str(raised.value)
    assert raised.value.usage is not None
    assert raised.value.usage["output_tokens"] == 7


@pytest.mark.parametrize("kind", ["content_block_delta", "content_block_stop"])
def test_an_event_for_a_block_never_started_raises_shape_error(kind: str) -> None:
    parser = ReplyParser()
    parser.feed(start())
    with pytest.raises(ShapeError, match="never started"):
        parser.feed(event(kind, index=3, delta={"type": "text_delta", "text": "x"}))


def test_a_first_event_that_isnt_message_start_raises_shape_error() -> None:
    with pytest.raises(ShapeError, match="not message_start"):
        ReplyParser().feed(event("content_block_start", index=0, content_block={"type": "text"}))


def test_a_message_start_without_a_message_raises_shape_error() -> None:
    with pytest.raises(ShapeError, match="no message"):
        ReplyParser().feed(event("message_start"))


def test_a_content_block_start_without_an_index_or_block_raises_shape_error() -> None:
    parser = ReplyParser()
    parser.feed(start())
    with pytest.raises(ShapeError, match="no index or block"):
        parser.feed(event("content_block_start", content_block={"type": "text"}))


def test_a_content_block_delta_without_a_delta_raises_shape_error() -> None:
    parser = ReplyParser()
    parser.feed(start())
    parser.feed(event("content_block_start", index=0, content_block={"type": "text", "text": ""}))
    with pytest.raises(ShapeError, match="no delta"):
        parser.feed(event("content_block_delta", index=0))


# Usage, and the prompt it reports (design D8)


def test_usage_is_merged_from_message_start_and_message_delta() -> None:
    reply = _parse(
        [
            start(used=usage(60, 1, cache_read=40, cache_write=10)),
            event(
                "message_delta",
                delta={"stop_reason": "end_turn"},
                usage={"output_tokens": 25, "input_tokens": None},
            ),
            event("message_stop"),
        ]
    )
    assert reply.usage == {
        "input_tokens": 60,
        "output_tokens": 25,
        "cache_read_input_tokens": 40,
        "cache_creation_input_tokens": 10,
    }


def test_a_reply_with_no_usage_anywhere_has_none() -> None:
    message = start()
    del message["message"]["usage"]
    reply = _parse(
        [message, event("message_delta", delta={"stop_reason": "end_turn"}), event("message_stop")]
    )
    assert reply.usage is None
    assert reply.prompt_tokens is None


@pytest.mark.parametrize(
    ("used", "prompt"),
    [
        (usage(60, 1, cache_read=40, cache_write=10), 110),
        (usage(60, 1, cache_read=None, cache_write=None), 60),
        (usage(0, 1, cache_read=5, cache_write=0), 5),
        ({"input_tokens": 60, "cache_read_input_tokens": -4, "output_tokens": 1}, 60),
        ({"input_tokens": 60, "cache_read_input_tokens": True, "output_tokens": 1}, 60),
    ],
    ids=["all three", "input alone", "zero input", "a negative counter", "a boolean counter"],
)
def test_prompt_tokens_sums_input_and_both_cache_counters(
    used: dict[str, Any], prompt: int
) -> None:
    assert _parse([start(used=used), *finish("end_turn")]).prompt_tokens == prompt


@pytest.mark.parametrize(
    "used",
    [
        {"output_tokens": 1, "cache_read_input_tokens": 40},
        {"input_tokens": None, "output_tokens": 1, "cache_read_input_tokens": 40},
        {"input_tokens": -1, "output_tokens": 1},
        {"input_tokens": True, "output_tokens": 1},
        {"input_tokens": "60", "output_tokens": 1},
    ],
    ids=repr,
)
def test_prompt_tokens_is_none_without_a_count_of_input_tokens(used: dict[str, Any]) -> None:
    assert _parse([start(used=used), *finish("end_turn")]).prompt_tokens is None


# Stop reason and details


def test_the_stop_reason_and_details_come_from_message_delta() -> None:
    details = {"type": "refusal", "category": "cyber"}
    reply = _parse([start(), *finish("refusal", stop_details=details)])
    assert (reply.stop_reason, reply.stop_details) == ("refusal", details)


def test_a_stop_reason_that_isnt_a_string_is_none() -> None:
    reply = _parse(
        [start(), event("message_delta", delta={"stop_reason": 3}), event("message_stop")]
    )
    assert reply.stop_reason is None


# Events the runner doesn't read


@pytest.mark.parametrize(
    "unknown",
    [
        event("ping"),
        event("a_later_event", index=0, delta={"type": "text_delta", "text": "x"}),
        event("content_block_delta", index=0, delta={"type": "a_later_delta", "x": 1}),
    ],
    ids=["ping", "unknown event", "unknown delta"],
)
def test_events_and_deltas_the_runner_doesnt_know_change_nothing(unknown: dict[str, Any]) -> None:
    plain = [start(), *text_block(0, "Hi."), *finish("end_turn")]
    expected = _parse(plain)
    mixed = [*plain[:2], unknown, *plain[2:]]
    assert _parse(mixed) == expected


def test_feed_returns_true_only_at_message_stop() -> None:
    parser = ReplyParser()
    events = [start(), *text_block(0, "Hi."), *finish("end_turn")]
    assert [parser.feed(item) for item in events] == [False] * (len(events) - 1) + [True]
