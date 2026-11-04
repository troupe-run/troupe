"""The tool loop, run in-process against the fake endpoint (spec: openai-chat-runner's loop
requirements; design D6, D7, D9). Every run uses TEST_LIMITS unless a test sets its own and says
why (design D7)."""

import json
import uuid
from pathlib import Path
from typing import Any

import pytest

from chat_harness import TEST_LIMITS
from fake_endpoint import (
    FakeEndpoint,
    Reply,
    chunk,
    error_reply,
    sse,
    text_reply,
    tool_reply,
    usage,
)
from troupe_plugin_sdk.effects import READ_ONLY, Effects
from troupe_plugin_sdk.events import EventNumbering, encoded_size
from troupe_plugin_sdk.runner import ResultEvent, RunEvent
from troupe_plugin_sdk.tools import Tools
from troupe_runner_openai_chat.defaults import INSTRUCTIONS
from troupe_runner_openai_chat.loop import Loop
from troupe_runner_openai_chat.options import parse_options
from troupe_runner_openai_chat.runtime import Runtime

MODEL = "fake-model"
"""The model the fake endpoint's chunks say answered, so a run notes no other model."""


class Ran:
    """A loop's run: what it sent, recorded and returned, and what the fake endpoint received."""

    def __init__(
        self,
        fake: FakeEndpoint,
        result: ResultEvent | None,
        events: list[RunEvent],
        records: list[dict[str, Any]],
    ) -> None:
        self.fake = fake
        self.result = result
        self.events = [e.to_data() for e in events]
        self.records = records

    @property
    def bodies(self) -> list[dict[str, Any]]:
        return [request.json() for request in self.fake.requests]

    def of(self, kind: str) -> list[dict[str, Any]]:
        return [e for e in self.events if e["type"] == kind]


def run(
    tmp_path: Path,
    script: list[Reply],
    options: dict[str, Any] | None = None,
    effects: Effects = READ_ONLY,
    character: str | None = None,
    direction: str = "Do the task.",
    event_max_bytes: int = 65536,
) -> Ran:
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    events: list[RunEvent] = []
    records: list[dict[str, Any]] = []
    with FakeEndpoint(script) as fake:
        loop = Loop(
            runtime=Runtime.checked(fake.endpoint, MODEL, "sk-canary-0123456789"),
            options=parse_options(TEST_LIMITS if options is None else options),
            tools=Tools(workspace, effects),
            numbering=EventNumbering(str(uuid.uuid4()), event_max_bytes, next_seq=1),
            send=events.append,
            record=records.append,
            wait=lambda _: False,
            exchange_limits={"base_delay": 0.0},
        )
        result = loop.run(direction, character)
    return Ran(fake, result, events, records)


def _result(ran: Ran) -> dict[str, Any]:
    assert ran.result is not None
    return ran.result.to_data()


# The conversation


def test_every_request_asks_for_the_runtimes_model(tmp_path: Path) -> None:
    ran = run(tmp_path, [tool_reply([("c1", "Glob", {"pattern": "*"})]), text_reply("Done.")])
    assert [b["model"] for b in ran.bodies] == [MODEL, MODEL]


def test_the_first_request_is_the_system_message_ending_with_the_character_then_the_direction(
    tmp_path: Path,
) -> None:
    ran = run(
        tmp_path, [text_reply("ok")], character="You are terse.", direction="Write out/hello.txt"
    )
    system, user = ran.bodies[0]["messages"]
    assert system == {"role": "system", "content": f"{INSTRUCTIONS}\n\nYou are terse."}
    assert user == {"role": "user", "content": "Write out/hello.txt"}


def test_without_a_character_the_system_message_is_only_the_instructions(tmp_path: Path) -> None:
    ran = run(tmp_path, [text_reply("ok")])
    assert ran.bodies[0]["messages"][0] == {"role": "system", "content": INSTRUCTIONS}


def test_each_request_offers_the_sdks_seven_tools_as_functions_streamed_with_usage(
    tmp_path: Path,
) -> None:
    body = run(tmp_path, [text_reply("ok")]).bodies[0]
    assert [t["function"]["name"] for t in body["tools"]] == [
        "Read",
        "Write",
        "Edit",
        "Glob",
        "Grep",
        "Delete",
        "Move",
    ]
    assert {t["type"] for t in body["tools"]} == {"function"}
    first = Tools.definitions()[0]
    assert body["tools"][0]["function"] == {
        "name": first.name,
        "description": first.description,
        "parameters": first.input_schema,
    }
    assert body["stream"] is True
    assert body["stream_options"] == {"include_usage": True}


# Tool calls


def test_a_write_a_read_only_actor_didnt_declare_is_refused_naming_the_effect(
    tmp_path: Path,
) -> None:
    script = [
        tool_reply([("c1", "Write", {"file_path": "out/hello.txt", "content": "hi"})]),
        text_reply("I couldn't."),
    ]
    ran = run(tmp_path, script)
    assert not (tmp_path / "workspace" / "out" / "hello.txt").exists()
    (result,) = ran.of("tool_result")
    assert result["isError"] is True
    assert "write effect" in result["outputSummary"]
    tool_message = ran.bodies[1]["messages"][-1]
    assert tool_message["role"] == "tool"
    assert "write effect" in tool_message["content"]


def test_a_declared_write_is_carried_out(tmp_path: Path) -> None:
    script = [
        tool_reply([("c1", "Write", {"file_path": "out/hello.txt", "content": "hi"})]),
        text_reply("Wrote it."),
    ]
    run(tmp_path, script, effects=Effects(write=("out/**",)))
    assert (tmp_path / "workspace" / "out" / "hello.txt").read_text(encoding="utf-8") == "hi"


def test_two_calls_in_one_response_run_in_order_and_answer_in_order(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "a.txt").write_text("A", encoding="utf-8")
    (workspace / "b.txt").write_text("B", encoding="utf-8")
    calls = [("ca", "Read", {"file_path": "a.txt"}), ("cb", "Read", {"file_path": "b.txt"})]
    ran = run(tmp_path, [tool_reply(calls), text_reply("Read both.")])
    pairs = [(e["type"], e["callId"]) for e in ran.events if e["type"].startswith("tool_")]
    assert pairs == [
        ("tool_call", "ca"),
        ("tool_result", "ca"),
        ("tool_call", "cb"),
        ("tool_result", "cb"),
    ]
    assistant, first, second = ran.bodies[1]["messages"][-3:]
    assert [c["id"] for c in assistant["tool_calls"]] == ["ca", "cb"]
    assert (first["tool_call_id"], second["tool_call_id"]) == ("ca", "cb")
    assert "A" in first["content"]
    assert "B" in second["content"]


def test_a_call_without_an_id_is_given_one_used_in_its_events_and_its_tool_message(
    tmp_path: Path,
) -> None:
    ran = run(tmp_path, [tool_reply([("", "Glob", {"pattern": "*"})]), text_reply("ok")])
    (call,) = ran.of("tool_call")
    assert call["callId"] == "call-1"
    assert ran.bodies[1]["messages"][-2]["tool_calls"][0]["id"] == "call-1"
    assert ran.bodies[1]["messages"][-1]["tool_call_id"] == "call-1"


def test_arguments_that_arent_json_are_an_error_result_the_model_is_sent(tmp_path: Path) -> None:
    ran = run(tmp_path, [tool_reply([("c1", "Write", '{"file_path": "a.txt"')]), text_reply("ok")])
    (result,) = ran.of("tool_result")
    assert result["isError"] is True
    assert "JSON" in result["outputSummary"]
    assert ran.bodies[1]["messages"][-1]["content"] == result["outputSummary"]
    assert _result(ran)["status"] == "ok"


# How a run ends


def test_a_reply_without_tool_calls_is_a_turn_then_an_ok_result_with_its_text(
    tmp_path: Path,
) -> None:
    ran = run(tmp_path, [text_reply("Wrote out/hello.txt.")])
    assert ran.of("turn") == [
        {
            "runId": ran.events[0]["runId"],
            "seq": 1,
            "type": "turn",
            "role": "assistant",
            "text": "Wrote out/hello.txt.",
        }
    ]
    result = _result(ran)
    assert (result["status"], result["message"], result["seq"]) == ("ok", "Wrote out/hello.txt.", 2)


def test_text_and_a_tool_call_send_the_turn_before_the_call(tmp_path: Path) -> None:
    script = [tool_reply([("c1", "Glob", {"pattern": "*"})], text="I'll look."), text_reply("ok")]
    kinds = [e["type"] for e in run(tmp_path, script).events]
    assert kinds[:3] == ["turn", "tool_call", "tool_result"]


def test_a_refusal_ends_the_run_with_an_error_holding_it(tmp_path: Path) -> None:
    refusal = Reply(
        lines=sse([chunk({"refusal": "I can't help with that."}), chunk(finish="stop")])
    )
    result = _result(run(tmp_path, [refusal]))
    assert result["status"] == "error"
    assert result["message"] == "The model refused: I can't help with that."


@pytest.mark.parametrize(
    ("finish", "words"),
    [
        ("content_filter", "content filter stopped the response"),
        ("length", "reached the service's output limit"),
        ("paused", "finished with 'paused'"),
    ],
)
def test_an_unexpected_finish_ends_the_run_with_an_error_naming_it(
    tmp_path: Path, finish: str, words: str
) -> None:
    reply = Reply(lines=sse([chunk({"content": "partial"}), chunk(finish=finish)]))
    ran = run(tmp_path, [reply])
    result = _result(ran)
    assert result["status"] == "error"
    assert words in result["message"]
    assert len(ran.fake.requests) == 1


def test_a_failed_exchange_is_an_error_result(tmp_path: Path) -> None:
    result = _result(run(tmp_path, [error_reply(401, "Incorrect API key provided")]))
    assert result["status"] == "error"
    assert result["message"].startswith("The service refused the credential (HTTP 401)")


def test_a_retry_is_sent_as_a_retry_event_before_the_next_request(tmp_path: Path) -> None:
    ran = run(tmp_path, [error_reply(503, "overloaded"), text_reply("ok")])
    (retry,) = ran.of("retry")
    assert {k: retry[k] for k in ("attempt", "maxAttempts", "reason", "delayMs")} == {
        "attempt": 1,
        "maxAttempts": 5,
        "reason": "server",
        "delayMs": 0,
    }
    assert retry["message"] == "HTTP 503: overloaded"


# The limits (each test sets the limit it checks, and says so)


def test_the_turn_limit_carries_out_the_last_replys_calls_then_ends_with_an_error(
    tmp_path: Path,
) -> None:
    script = [tool_reply([(f"c{n}", "Glob", {"pattern": "*"})]) for n in range(4)]
    ran = run(tmp_path, script, options={**TEST_LIMITS, "maxTurns": 3})  # the limit under test
    assert len(ran.fake.requests) == 3
    assert len(ran.of("tool_result")) == 3
    result = _result(ran)
    assert result["status"] == "error"
    assert "turn limit of 3 was reached" in result["message"]


def test_a_spent_token_budget_carries_out_the_calls_then_ends_naming_the_tokens(
    tmp_path: Path,
) -> None:
    script = [tool_reply([("c1", "Glob", {"pattern": "*"})], prompt=1100, completion=100)] * 2
    ran = run(tmp_path, script, options={"maxTurns": 5, "maxTotalTokens": 1000})  # under test
    assert len(ran.fake.requests) == 1
    assert len(ran.of("tool_result")) == 1
    result = _result(ran)
    assert result["status"] == "error"
    assert "token budget of 1000 was spent" in result["message"]
    assert "1200 tokens" in result["message"]


# Usage and cost


def _usage_reply(text: str, **record: Any) -> Reply:  # noqa: ANN401
    return Reply(lines=sse([chunk({"content": text}), chunk(finish="stop"), chunk(usage=record)]))


def test_usage_is_summed_with_cached_input_counted_apart(tmp_path: Path) -> None:
    first = tool_reply([("c1", "Glob", {"pattern": "*"})])
    first = Reply(
        lines=[
            line.replace('"prompt_tokens": 10', '"prompt_tokens": 100')
            .replace('"cached_tokens": 0', '"cached_tokens": 40')
            .replace('"completion_tokens": 5', '"completion_tokens": 10')
            if isinstance(line, str)
            else line
            for line in first.lines or []
        ]
    )
    second = _usage_reply("ok", **usage(200, 20))
    result = _result(run(tmp_path, [first, second]))
    assert result["usage"] == {"inputTokens": 260, "outputTokens": 30, "cacheReadTokens": 40}
    assert result["turns"] == 2


def test_a_service_that_reports_no_usage_gets_a_warning_and_a_result_without_usage(
    tmp_path: Path,
) -> None:
    no_usage = Reply(lines=sse([chunk({"content": "ok"}), chunk(finish="stop")]))
    ran = run(tmp_path, [no_usage])
    (warning,) = ran.of("log")
    assert warning["level"] == "warning"
    assert "reported no usage" in warning["message"]
    assert "usage" not in _result(ran)


def test_a_service_that_reports_no_cost_gives_a_result_without_cost(tmp_path: Path) -> None:
    assert "costUsd" not in _result(run(tmp_path, [text_reply("ok")]))


def test_costs_the_service_reports_are_summed(tmp_path: Path) -> None:
    first = Reply(
        lines=sse(
            [
                chunk(
                    {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "c1",
                                "function": {"name": "Glob", "arguments": '{"pattern": "*"}'},
                            }
                        ]
                    }
                ),
                chunk(finish="tool_calls"),
                chunk(usage=usage(10, 5, cost=0.001)),
            ]
        )
    )
    result = _result(run(tmp_path, [first, _usage_reply("ok", **usage(10, 5, cost=0.002))]))
    assert result["costUsd"] == pytest.approx(0.003)


def test_a_model_other_than_the_one_asked_for_is_noted_once(tmp_path: Path) -> None:
    reply = Reply(
        lines=sse(
            [
                chunk({"content": "ok"}, model="fake-model-2026"),
                chunk(finish="stop", model="fake-model-2026"),
                chunk(usage=usage(1, 1), model="fake-model-2026"),
            ]
        )
    )
    (note,) = run(tmp_path, [reply]).of("log")
    assert note["level"] == "info"
    assert "fake-model-2026" in note["message"]


# Sizes


def test_a_long_final_reply_is_cut_to_fit_in_its_turn_and_its_result(tmp_path: Path) -> None:
    long = "x" * (1024 * 1024)
    ran = run(tmp_path, [text_reply(long)], event_max_bytes=65536)
    turn = ran.of("turn")[0]
    result = _result(ran)
    for event, key in ((turn, "text"), (result, "message")):
        assert encoded_size(event) <= 65536
        assert event[key].endswith("bytes left out]")


def test_the_events_validate_as_the_contracts_run_events(tmp_path: Path) -> None:
    from chat_harness import validator

    ran = run(
        tmp_path, [tool_reply([("c1", "Glob", {"pattern": "*"})], text="look"), text_reply("ok")]
    )
    check = validator("run-event.schema.json#/$defs/event")
    for event in [*ran.events, _result(ran)]:
        assert check.is_valid(event), json.dumps(event)
