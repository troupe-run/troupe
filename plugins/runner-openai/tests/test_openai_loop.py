"""The tool loop over the Responses API, run in-process against the fake endpoint (spec:
openai-runner's loop requirements; design D6, D7, D9). Every run uses TEST_LIMITS unless a test sets
its own and says why (design D7)."""

import json
import uuid
from pathlib import Path
from typing import Any

import pytest

from fake_endpoint import (
    FakeEndpoint,
    Reply,
    error_reply,
    final,
    message,
    reasoning,
    refusal,
    sse,
    status_reply,
    text_reply,
    tool_reply,
    usage,
)
from openai_harness import TEST_LIMITS, check_limits, validator
from troupe_plugin_sdk.effects import READ_ONLY, Effects
from troupe_plugin_sdk.events import EventNumbering, encoded_size
from troupe_plugin_sdk.runner import ResultEvent, RunEvent
from troupe_plugin_sdk.tools import Tools
from troupe_runner_openai.defaults import INSTRUCTIONS
from troupe_runner_openai.loop import Loop
from troupe_runner_openai.options import parse_options
from troupe_runner_openai.runtime import Runtime

MODEL = "fake-model"
"""The model the fake endpoint's responses say answered, so a run notes no other model."""


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
    options = TEST_LIMITS if options is None else options
    check_limits(options, None)
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    events: list[RunEvent] = []
    records: list[dict[str, Any]] = []
    with FakeEndpoint(script) as fake:
        loop = Loop(
            runtime=Runtime.checked(fake.endpoint, MODEL, "sk-canary-0123456789"),
            options=parse_options(options),
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


GLOB = ("c1", "Glob", {"pattern": "*"})


# The request


def test_every_request_goes_to_responses_asking_for_the_runtimes_model(tmp_path: Path) -> None:
    ran = run(tmp_path, [tool_reply([GLOB]), text_reply("Done.")])
    assert [r.path for r in ran.fake.requests] == ["/v1/responses", "/v1/responses"]
    assert [b["model"] for b in ran.bodies] == [MODEL, MODEL]


def test_the_character_follows_the_instructions_and_the_direction_is_the_first_input(
    tmp_path: Path,
) -> None:
    ran = run(
        tmp_path, [text_reply("ok")], character="You are terse.", direction="Write out/hello.txt"
    )
    body = ran.bodies[0]
    assert body["instructions"] == f"{INSTRUCTIONS}\n\nYou are terse."
    assert body["input"] == [{"role": "user", "content": "Write out/hello.txt"}]


def test_without_a_character_the_instructions_are_only_the_runners(tmp_path: Path) -> None:
    assert run(tmp_path, [text_reply("ok")]).bodies[0]["instructions"] == INSTRUCTIONS


def test_every_request_is_streamed_stored_nowhere_and_asks_for_encrypted_reasoning(
    tmp_path: Path,
) -> None:
    for body in run(tmp_path, [tool_reply([GLOB]), text_reply("ok")]).bodies:
        assert body["stream"] is True
        assert body["store"] is False
        assert "previous_response_id" not in body
        assert body["include"] == ["reasoning.encrypted_content"]


def test_each_request_offers_the_sdks_seven_tools_as_functions_that_arent_strict(
    tmp_path: Path,
) -> None:
    tools = run(tmp_path, [text_reply("ok")]).bodies[0]["tools"]
    assert [t["name"] for t in tools] == ["Read", "Write", "Edit", "Glob", "Grep", "Delete", "Move"]
    first = Tools.definitions()[0]
    assert tools[0] == {
        "type": "function",
        "name": first.name,
        "description": first.description,
        "parameters": first.input_schema,
        "strict": False,
    }


# Tool calls


def test_a_write_a_read_only_actor_didnt_declare_is_refused_naming_the_effect(
    tmp_path: Path,
) -> None:
    write = ("c1", "Write", {"file_path": "out/hello.txt", "content": "hi"})
    ran = run(tmp_path, [tool_reply([write]), text_reply("I couldn't.")])
    assert not (tmp_path / "workspace" / "out" / "hello.txt").exists()
    (result,) = ran.of("tool_result")
    assert result["isError"] is True
    assert "write effect" in result["outputSummary"]
    sent = ran.bodies[1]["input"][-1]
    assert (sent["type"], sent["call_id"]) == ("function_call_output", "c1")
    assert "write effect" in sent["output"]


def test_a_declared_write_is_carried_out(tmp_path: Path) -> None:
    write = ("c1", "Write", {"file_path": "out/hello.txt", "content": "hi"})
    run(
        tmp_path, [tool_reply([write]), text_reply("Wrote it.")], effects=Effects(write=("out/**",))
    )
    assert (tmp_path / "workspace" / "out" / "hello.txt").read_text(encoding="utf-8") == "hi"


def test_two_calls_run_in_order_and_the_next_input_sends_the_output_back_then_both_answers(
    tmp_path: Path,
) -> None:
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
    second = ran.bodies[1]["input"]
    assert second[0] == ran.bodies[0]["input"][0]
    assert [i["type"] for i in second[1:]] == [
        "function_call",
        "function_call",
        "function_call_output",
        "function_call_output",
    ]
    assert [i["call_id"] for i in second[3:]] == ["ca", "cb"]
    assert "A" in second[3]["output"]
    assert "B" in second[4]["output"]


def test_reasoning_is_sent_back_unchanged_before_its_call(tmp_path: Path) -> None:
    thought = reasoning("look first")
    ran = run(tmp_path, [tool_reply([GLOB], before=[thought]), text_reply("ok")])
    sent = ran.bodies[1]["input"]
    assert sent[1] == thought
    assert sent[2]["type"] == "function_call"


def test_a_call_without_a_call_id_ends_the_run_naming_its_tool(tmp_path: Path) -> None:
    ran = run(tmp_path, [tool_reply([(None, "Glob", {"pattern": "*"})])])
    result = _result(ran)
    assert result["status"] == "error"
    assert "no call_id" in result["message"]
    assert "Glob" in result["message"]
    assert ran.of("tool_call") == []


def test_arguments_that_arent_json_are_an_error_result_the_model_is_sent(tmp_path: Path) -> None:
    ran = run(tmp_path, [tool_reply([("c1", "Write", '{"file_path": "a.txt"')]), text_reply("ok")])
    (result,) = ran.of("tool_result")
    assert result["isError"] is True
    assert "JSON" in result["outputSummary"]
    assert ran.bodies[1]["input"][-1]["output"] == result["outputSummary"]
    assert _result(ran)["status"] == "ok"


# How a run ends


def test_a_completed_reply_without_calls_is_a_turn_then_an_ok_result_with_its_text(
    tmp_path: Path,
) -> None:
    ran = run(tmp_path, [text_reply("Wrote out/hello.txt.")])
    assert [e["text"] for e in ran.of("turn")] == ["Wrote out/hello.txt."]
    result = _result(ran)
    assert (result["status"], result["message"], result["seq"]) == ("ok", "Wrote out/hello.txt.", 2)


def test_text_and_a_tool_call_send_the_turn_before_the_call(tmp_path: Path) -> None:
    script = [tool_reply([GLOB], text="I'll look."), text_reply("ok")]
    kinds = [e["type"] for e in run(tmp_path, script).events]
    assert kinds[:3] == ["turn", "tool_call", "tool_result"]


def test_a_refusal_ends_the_run_with_an_error_holding_it(tmp_path: Path) -> None:
    refused = Reply(lines=sse([final([refusal("I can't help with that.")], used=usage(1, 1))]))
    result = _result(run(tmp_path, [refused]))
    assert (result["status"], result["message"]) == (
        "error",
        "The model refused: I can't help with that.",
    )


@pytest.mark.parametrize(
    ("reason", "words"),
    [
        ("max_output_tokens", "reached the service's output limit"),
        ("content_filter", "content filter stopped the response"),
        ("something_new", "left incomplete (something_new)"),
    ],
)
def test_an_incomplete_response_ends_the_run_with_an_error_naming_why(
    tmp_path: Path, reason: str, words: str
) -> None:
    ran = run(tmp_path, [status_reply("incomplete", [message("partial")], incomplete=reason)])
    result = _result(ran)
    assert result["status"] == "error"
    assert words in result["message"]
    assert len(ran.fake.requests) == 1


def test_a_status_the_runner_doesnt_know_ends_the_run_naming_it(tmp_path: Path) -> None:
    paused = final([message("hm")], used=usage(1, 1))
    paused["response"]["status"] = "paused"
    result = _result(run(tmp_path, [Reply(lines=sse([paused]))]))
    assert result["status"] == "error"
    assert "'paused'" in result["message"]


def test_a_failed_exchange_is_an_error_result(tmp_path: Path) -> None:
    result = _result(run(tmp_path, [error_reply(401, "Incorrect API key provided")]))
    assert result["status"] == "error"
    assert result["message"].startswith("The service refused the credential (HTTP 401)")


def test_a_retry_is_sent_as_a_retry_event_before_the_next_request(tmp_path: Path) -> None:
    ran = run(tmp_path, [error_reply(503, "overloaded"), text_reply("ok")])
    (retry,) = ran.of("retry")
    assert {k: retry[k] for k in ("attempt", "maxAttempts", "reason", "delayMs", "message")} == {
        "attempt": 1,
        "maxAttempts": 5,
        "reason": "server",
        "delayMs": 0,
        "message": "HTTP 503: overloaded",
    }


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
    script = [tool_reply([GLOB], prompt=1100, completion=100)] * 2
    ran = run(tmp_path, script, options={"maxTurns": 5, "maxTotalTokens": 1000})  # under test
    assert len(ran.fake.requests) == 1
    assert len(ran.of("tool_result")) == 1
    result = _result(ran)
    assert result["status"] == "error"
    assert "token budget of 1000 was spent" in result["message"]
    assert "1200 tokens" in result["message"]


# Usage and cost


def _used(text: str, used: dict[str, Any] | None) -> Reply:
    return Reply(lines=sse([final([message(text)], used=used)]))


def _called(used: dict[str, Any]) -> Reply:
    reply = tool_reply([GLOB])
    lines = [line for line in reply.lines or [] if isinstance(line, str)]
    *_, data, _blank = lines
    final_event = json.loads(data[6:])
    final_event["response"]["usage"] = used
    return Reply(lines=[*lines[:-2], f"data: {json.dumps(final_event)}", ""])


def test_usage_is_summed_with_cached_input_counted_apart(tmp_path: Path) -> None:
    script = [_called(usage(100, 10, cached=40)), _used("ok", usage(200, 20))]
    result = _result(run(tmp_path, script))
    assert result["usage"] == {"inputTokens": 260, "outputTokens": 30, "cacheReadTokens": 40}
    assert result["turns"] == 2


def test_tokens_written_to_the_cache_are_counted_apart_too(tmp_path: Path) -> None:
    result = _result(run(tmp_path, [_used("ok", usage(300, 10, cached=100, cache_write=50))]))
    assert result["usage"] == {
        "inputTokens": 150,
        "outputTokens": 10,
        "cacheReadTokens": 100,
        "cacheWriteTokens": 50,
    }


def test_a_service_that_reports_no_usage_gets_a_warning_and_a_result_without_usage(
    tmp_path: Path,
) -> None:
    ran = run(tmp_path, [_used("ok", None)])
    (warning,) = ran.of("log")
    assert warning["level"] == "warning"
    assert "reported no usage" in warning["message"]
    assert "usage" not in _result(ran)


def _wrong_shape(used: dict[str, Any] | None) -> Reply:
    """A completed response whose output isn't a list, with ``used`` as its usage."""
    done = final([message("x")], used=used)
    done["response"]["output"] = 3
    return Reply(lines=sse([done]))


def test_a_wrong_shaped_responses_readable_usage_and_cost_are_counted_into_the_error_result(
    tmp_path: Path,
) -> None:
    script = [
        _called(usage(100, 10, cost=0.001)),
        _wrong_shape(usage(200, 20, cost=0.002)),
    ]
    ran = run(tmp_path, script)
    result = _result(ran)
    assert result["status"] == "error"
    assert "output isn't a list" in result["message"]
    assert result["usage"] == {"inputTokens": 300, "outputTokens": 30, "cacheReadTokens": 0}
    assert result["costUsd"] == 0.003
    assert result["turns"] == 2
    assert len(ran.fake.requests) == 2


def test_a_wrong_shaped_response_whose_usage_cant_be_read_leaves_the_result_without_usage(
    tmp_path: Path,
) -> None:
    done = final([message("x")], used=usage(200, 20))
    done["response"]["output"] = 3
    done["response"]["usage"] = "lots"
    result = _result(run(tmp_path, [_called(usage(100, 10)), Reply(lines=sse([done]))]))
    assert result["status"] == "error"
    assert "usage" not in result
    assert result["turns"] == 2


def test_a_failure_with_no_response_counts_no_turn_or_usage(tmp_path: Path) -> None:
    result = _result(run(tmp_path, [_called(usage(100, 10)), error_reply(401, "no")]))
    assert result["usage"] == {"inputTokens": 100, "outputTokens": 10, "cacheReadTokens": 0}
    assert result["turns"] == 1


def test_a_service_that_reports_no_cost_gives_a_result_without_cost(tmp_path: Path) -> None:
    assert "costUsd" not in _result(run(tmp_path, [text_reply("ok")]))


def test_costs_the_service_reports_are_summed(tmp_path: Path) -> None:
    script = [_called(usage(10, 5, cost=0.001)), _used("ok", usage(10, 5, cost=0.002))]
    assert _result(run(tmp_path, script))["costUsd"] == pytest.approx(0.003)


def test_a_model_other_than_the_one_asked_for_is_noted_once(tmp_path: Path) -> None:
    reply = Reply(lines=sse([final([message("ok")], used=usage(1, 1), model="fake-model-2026")]))
    (note,) = run(tmp_path, [reply]).of("log")
    assert note["level"] == "info"
    assert "fake-model-2026" in note["message"]


# Sizes, and the contract


def test_a_long_final_reply_is_cut_to_fit_in_its_turn_and_its_result(tmp_path: Path) -> None:
    ran = run(tmp_path, [text_reply("x" * (1024 * 1024))], event_max_bytes=65536)
    turn = ran.of("turn")[0]
    result = _result(ran)
    for event, key in ((turn, "text"), (result, "message")):
        assert encoded_size(event) <= 65536
        assert event[key].endswith("bytes left out]")


def test_the_events_validate_as_the_contracts_run_events(tmp_path: Path) -> None:
    ran = run(tmp_path, [tool_reply([GLOB], text="look"), text_reply("ok")])
    check = validator("run-event.schema.json#/$defs/event")
    for event in [*ran.events, _result(ran)]:
        assert check.is_valid(event), event


def test_a_stop_after_one_call_carries_out_none_of_the_rest(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    first = ("c1", "Write", {"file_path": "a.txt", "content": "a"})
    second = ("c2", "Write", {"file_path": "b.txt", "content": "b"})
    with FakeEndpoint([tool_reply([first, second])]) as fake:
        loop = Loop(
            runtime=Runtime.checked(fake.endpoint, MODEL, None),
            options=parse_options(TEST_LIMITS),
            tools=Tools(workspace, Effects(write=("*.txt",))),
            numbering=EventNumbering(str(uuid.uuid4()), 65536, next_seq=1),
            send=lambda _: None,
            record=lambda _: None,
            wait=lambda _: False,
            stopping=(workspace / "a.txt").exists,
        )
        assert loop.run("Write both.", None) is None
    assert (workspace / "a.txt").exists()
    assert not (workspace / "b.txt").exists()
    assert len(fake.requests) == 1


def test_a_last_reply_past_the_budget_ends_the_run_ok_reporting_what_it_used(
    tmp_path: Path,
) -> None:
    ran = run(tmp_path, [text_reply("Done.", 900, 300)], {**TEST_LIMITS, "maxTotalTokens": 1000})
    result = _result(ran)
    assert result["status"] == "ok"
    assert result["usage"]["inputTokens"] + result["usage"]["outputTokens"] == 1200
