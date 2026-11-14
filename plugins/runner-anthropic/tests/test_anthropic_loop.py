"""The tool loop over the Messages API, run in-process with the real service seam against the fake
Messages API (spec: anthropic-runner's loop requirements; design D2, D5, D7, D8, D11). Every run
uses TEST_LIMITS unless a test sets its own and says why."""

import json
import os
import uuid
from pathlib import Path
from typing import Any

import pytest

from anthropic_harness import CANARY, TEST_LIMITS, check_limits, validator
from fake_messages import (
    FakeEndpoint,
    Reply,
    error_reply,
    finish,
    sse,
    start,
    stream_error_reply,
    text_block,
    text_reply,
    tool_reply,
)
from troupe_plugin_sdk.compaction import stub
from troupe_plugin_sdk.declaration import Declaration
from troupe_plugin_sdk.effects import READ_ONLY, Effects
from troupe_plugin_sdk.events import EventNumbering, encoded_size
from troupe_plugin_sdk.runner import Price, ResultEvent, RunEvent
from troupe_plugin_sdk.tools import Tools
from troupe_runner_anthropic.defaults import DEFAULT_MAX_OUTPUT_TOKENS, INSTRUCTIONS
from troupe_runner_anthropic.loop import Loop
from troupe_runner_anthropic.options import parse_options
from troupe_runner_anthropic.runtime import Runtime
from troupe_runner_anthropic.service import Service

MODEL = "fake-model"
"""The model the fake's replies say answered, so a run notes no other model."""


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """The service removes every ANTHROPIC_* variable from the process: monkeypatch puts back any
    the machine had once the test is done."""
    for name in [n for n in os.environ if n.upper().startswith("ANTHROPIC_")]:
        monkeypatch.delenv(name)


class Ran:
    """A loop's run: what it sent, recorded and returned, and what the fake received."""

    def __init__(
        self,
        fake: FakeEndpoint,
        result: ResultEvent | None,
        events: list[RunEvent],
        records: list[tuple[str, bytes]],
        workspace: Path,
    ) -> None:
        self.fake = fake
        self.result = result
        self.events = [e.to_data() for e in events]
        self.records = records
        self.workspace = workspace

    @property
    def bodies(self) -> list[dict[str, Any]]:
        return [request.json() for request in self.fake.requests]

    def of(self, kind: str) -> list[dict[str, Any]]:
        return [e for e in self.events if e["type"] == kind]


def _workspace(tmp_path: Path, files: dict[str, str] | None = None) -> tuple[Path, Path]:
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    scratch = tmp_path / "scratch"
    scratch.mkdir(exist_ok=True)
    for name, text in (files or {}).items():
        (workspace / name).write_text(text, encoding="utf-8")
    return workspace, scratch


def run(
    tmp_path: Path,
    script: list[Reply],
    options: dict[str, Any] | None = None,
    effects: Effects = READ_ONLY,
    character: str | None = None,
    direction: str = "Do the task.",
    event_max_bytes: int = 65536,
    price: Price | None = None,
    compact: bool = False,
    files: dict[str, str] | None = None,
    model: str = MODEL,
) -> Ran:
    options = TEST_LIMITS if options is None else options
    check_limits(options, None)
    workspace, scratch = _workspace(tmp_path, files)
    events: list[RunEvent] = []
    records: list[tuple[str, bytes]] = []
    with FakeEndpoint(script) as fake:
        runtime = Runtime.checked(fake.endpoint, model, CANARY, price)
        service = Service(runtime)
        try:
            loop = Loop(
                runtime=runtime,
                options=parse_options(options),
                tools=Tools.for_declaration(Declaration(effects, workspace, scratch)),
                numbering=EventNumbering(str(uuid.uuid4()), event_max_bytes, next_seq=1),
                open=service.stream,
                send=events.append,
                record=lambda kind, data: records.append((kind, data)),
                wait=lambda _: False,
                exchange_limits={"base_delay": 0.0},
                compact=compact,
            )
            result = loop.run(direction, character)
        finally:
            service.close()
    return Ran(fake, result, events, records, workspace)


def _result(ran: Ran) -> dict[str, Any]:
    assert ran.result is not None
    return ran.result.to_data()


def _tool_results(message: dict[str, Any]) -> list[dict[str, Any]]:
    content = message["content"]
    assert isinstance(content, list)
    return [block for block in content if block["type"] == "tool_result"]


GLOB = ("t1", "Glob", {"pattern": "*"})


# Requirement: The runner talks to its service only through the anthropic package; The service
# comes from the run's runtime; Each request asks for the run's output limit


def test_every_request_is_a_streamed_post_to_v1_messages_asking_for_the_runtimes_model(
    tmp_path: Path,
) -> None:
    ran = run(tmp_path, [tool_reply([GLOB]), text_reply("Done.")], model="small-model")
    assert [(r.method, r.path) for r in ran.fake.requests] == [("POST", "/v1/messages")] * 2
    assert [(b["model"], b["stream"]) for b in ran.bodies] == [("small-model", True)] * 2


def test_without_max_output_tokens_each_request_asks_for_the_named_default(tmp_path: Path) -> None:
    ran = run(tmp_path, [tool_reply([GLOB]), text_reply("Done.")])
    assert [b["max_tokens"] for b in ran.bodies] == [DEFAULT_MAX_OUTPUT_TOKENS] * 2


def test_max_output_tokens_is_each_requests_max_tokens(tmp_path: Path) -> None:
    ran = run(
        tmp_path,
        [tool_reply([GLOB]), text_reply("Done.")],
        options={**TEST_LIMITS, "maxOutputTokens": 2048},
    )
    assert [b["max_tokens"] for b in ran.bodies] == [2048, 2048]


# Requirement: The character is the system prompt and the direction the first message


def test_the_system_is_the_instructions_then_the_character_and_the_direction_the_one_message(
    tmp_path: Path,
) -> None:
    ran = run(
        tmp_path, [text_reply("ok")], character="You are terse.", direction="Write out/hello.txt"
    )
    body = ran.bodies[0]
    assert body["system"] == f"{INSTRUCTIONS}\n\nYou are terse."
    assert body["messages"] == [{"role": "user", "content": "Write out/hello.txt"}]


def test_without_a_character_the_system_is_only_the_runners_instructions(tmp_path: Path) -> None:
    assert run(tmp_path, [text_reply("ok")]).bodies[0]["system"] == INSTRUCTIONS


# Requirement: The model is offered the SDK's tools


def test_each_request_offers_the_sdks_tools_in_order_with_their_definitions_unchanged(
    tmp_path: Path,
) -> None:
    ran = run(tmp_path, [text_reply("ok")])
    expected = [
        {"name": t.name, "description": t.description, "input_schema": t.input_schema}
        for t in Tools.definitions(tmp_path / "scratch")
    ]
    assert ran.bodies[0]["tools"] == expected
    assert [t["name"] for t in expected] == Tools.names()


# Requirement: The runner applies the effects by checking each call


def test_a_write_a_read_only_actor_didnt_declare_is_refused_and_sent_back_as_an_error(
    tmp_path: Path,
) -> None:
    write = ("t1", "Write", {"file_path": "out/hello.txt", "content": "hi"})
    ran = run(tmp_path, [tool_reply([write]), text_reply("I couldn't.")])
    assert not (ran.workspace / "out" / "hello.txt").exists()
    (result,) = ran.of("tool_result")
    assert result["isError"] is True
    assert "write effect" in result["outputSummary"]
    (sent,) = _tool_results(ran.bodies[1]["messages"][-1])
    assert (sent["tool_use_id"], sent["is_error"]) == ("t1", True)
    assert "write effect" in sent["content"]


def test_a_declared_write_is_carried_out_and_sent_back_without_is_error(tmp_path: Path) -> None:
    write = ("t1", "Write", {"file_path": "out/hello.txt", "content": "hi"})
    ran = run(
        tmp_path, [tool_reply([write]), text_reply("Wrote it.")], effects=Effects(write=("out/**",))
    )
    assert (ran.workspace / "out" / "hello.txt").read_text(encoding="utf-8") == "hi"
    (sent,) = _tool_results(ran.bodies[1]["messages"][-1])
    assert "is_error" not in sent


# Requirement: Tool calls are carried out in order and answered in the next request


def test_two_calls_run_in_order_and_the_next_request_answers_both_in_one_user_message(
    tmp_path: Path,
) -> None:
    calls = [("ta", "Read", {"file_path": "a.txt"}), ("tb", "Read", {"file_path": "b.txt"})]
    ran = run(
        tmp_path, [tool_reply(calls), text_reply("Read both.")], files={"a.txt": "A", "b.txt": "B"}
    )
    pairs = [(e["type"], e["callId"]) for e in ran.events if e["type"].startswith("tool_")]
    assert pairs == [
        ("tool_call", "ta"),
        ("tool_result", "ta"),
        ("tool_call", "tb"),
        ("tool_result", "tb"),
    ]
    first, second = ran.bodies
    messages = second["messages"]
    assert len(messages) == 3
    assert messages[0] == first["messages"][0]
    assert messages[1] == {
        "role": "assistant",
        "content": [
            {"type": "tool_use", "id": "ta", "name": "Read", "input": {"file_path": "a.txt"}},
            {"type": "tool_use", "id": "tb", "name": "Read", "input": {"file_path": "b.txt"}},
        ],
    }
    assert messages[2]["role"] == "user"
    answers = _tool_results(messages[2])
    assert len(answers) == len(messages[2]["content"]) == 2
    assert [a["tool_use_id"] for a in answers] == ["ta", "tb"]
    assert "A" in answers[0]["content"]
    assert "B" in answers[1]["content"]


def test_a_thinking_block_is_sent_back_unchanged_with_its_signature_before_the_tool_use(
    tmp_path: Path,
) -> None:
    ran = run(tmp_path, [tool_reply([GLOB], thinking="Look first."), text_reply("ok")])
    content = ran.bodies[1]["messages"][1]["content"]
    assert content[0] == {"type": "thinking", "thinking": "Look first.", "signature": "sig-fake"}
    assert content[1]["type"] == "tool_use"
    assert all("Look first." not in json.dumps(e) for e in ran.events)


# Requirement: A malformed tool call is answered, not fatal


def test_a_tool_the_sdk_doesnt_have_is_an_error_naming_the_tools_and_the_run_goes_on(
    tmp_path: Path,
) -> None:
    ran = run(tmp_path, [tool_reply([("t1", "Bash", {"command": "ls"})]), text_reply("ok")])
    (result,) = ran.of("tool_result")
    assert result["isError"] is True
    assert all(name in result["outputSummary"] for name in Tools.names())
    (sent,) = _tool_results(ran.bodies[1]["messages"][-1])
    assert (sent["tool_use_id"], sent["is_error"]) == ("t1", True)
    assert _result(ran)["status"] == "ok"


def test_input_that_isnt_json_is_an_error_and_the_block_goes_back_with_an_empty_input(
    tmp_path: Path,
) -> None:
    ran = run(tmp_path, [tool_reply([("t1", "Write", '{"file_path": "a.txt"')]), text_reply("ok")])
    (result,) = ran.of("tool_result")
    assert result["isError"] is True
    assert "isn't valid JSON" in result["outputSummary"]
    assistant, answer = ran.bodies[1]["messages"][1:]
    assert assistant["content"] == [{"type": "tool_use", "id": "t1", "name": "Write", "input": {}}]
    (sent,) = _tool_results(answer)
    assert sent["is_error"] is True
    assert sent["content"] == result["outputSummary"]
    assert _result(ran)["status"] == "ok"


def test_a_tool_use_without_an_id_ends_the_run_with_engine_and_carries_out_nothing(
    tmp_path: Path,
) -> None:
    ran = run(tmp_path, [tool_reply([(None, "Glob", {"pattern": "*"})])])
    result = _result(ran)
    assert (result["status"], result["reason"]) == ("error", "engine")
    assert "has no id" in result["message"]
    assert ran.of("tool_call") == []
    assert ran.of("retry") == []


# Requirement: A finished reply without tool calls ends the run; Assistant text is reported as
# turns


@pytest.mark.parametrize("stop_reason", ["end_turn", "stop_sequence"])
def test_a_finished_reply_is_a_turn_then_an_ok_result_with_its_text(
    tmp_path: Path, stop_reason: str
) -> None:
    ran = run(tmp_path, [text_reply("Wrote out/hello.txt.", stop_reason=stop_reason)])
    assert [(e["type"], e.get("text")) for e in ran.events] == [("turn", "Wrote out/hello.txt.")]
    result = _result(ran)
    assert (result["status"], result["message"], result["seq"]) == ("ok", "Wrote out/hello.txt.", 2)


def test_text_and_a_tool_call_send_the_turn_before_the_call(tmp_path: Path) -> None:
    script = [tool_reply([GLOB], text="I'll look."), text_reply("ok")]
    ran = run(tmp_path, script)
    assert [e["type"] for e in ran.events][:3] == ["turn", "tool_call", "tool_result"]
    assert ran.events[0]["text"] == "I'll look."


# Requirement: A reply that stops for another reason ends the run with an error


def test_a_refusal_ends_with_refused_holding_its_text_and_details(tmp_path: Path) -> None:
    details = {"type": "refusal", "category": "cyber"}
    refused = Reply(
        lines=sse(
            [start(), *text_block(0, "I can't help."), *finish("refusal", stop_details=details)]
        )
    )
    ran = run(tmp_path, [refused])
    result = _result(ran)
    assert (result["status"], result["reason"]) == ("error", "refused")
    assert result["message"].startswith("The model refused")
    assert '"category": "cyber"' in result["message"]
    assert result["message"].endswith(": I can't help.")
    assert len(ran.fake.requests) == 1


def test_the_output_limit_inside_a_tool_call_carries_out_nothing_and_ends_output_limit(
    tmp_path: Path,
) -> None:
    cut = tool_reply(
        [("t1", "Write", '{"file_path": "a.txt", "content": "par')], stop_reason="max_tokens"
    )
    ran = run(tmp_path, [cut], effects=Effects(write=("*.txt",)))
    assert ran.of("tool_call") == []
    assert not (ran.workspace / "a.txt").exists()
    result = _result(ran)
    assert (result["status"], result["reason"]) == ("error", "output-limit")
    assert len(ran.fake.requests) == 1


def test_the_models_context_window_stop_ends_context_length(tmp_path: Path) -> None:
    ran = run(tmp_path, [text_reply("part", stop_reason="model_context_window_exceeded")])
    result = _result(ran)
    assert (result["status"], result["reason"]) == ("error", "context-length")
    assert len(ran.fake.requests) == 1


@pytest.mark.parametrize("stop_reason", ["pause_turn", "something_new"])
def test_any_other_stop_reason_ends_engine_naming_it(tmp_path: Path, stop_reason: str) -> None:
    result = _result(run(tmp_path, [text_reply("hm", stop_reason=stop_reason)]))
    assert (result["status"], result["reason"]) == ("error", "engine")
    assert repr(stop_reason) in result["message"]


def test_a_tool_use_stop_without_a_tool_use_block_ends_engine(tmp_path: Path) -> None:
    result = _result(run(tmp_path, [text_reply("hm", stop_reason="tool_use")]))
    assert (result["status"], result["reason"]) == ("error", "engine")
    assert "asked for none" in result["message"]


def test_a_failed_exchange_is_an_error_result_with_the_tables_reason(tmp_path: Path) -> None:
    ran = run(tmp_path, [error_reply(401, "invalid x-api-key", "authentication_error")])
    result = _result(ran)
    assert (result["status"], result["reason"]) == ("error", "authentication")
    assert "invalid x-api-key" in result["message"]
    assert len(ran.fake.requests) == 1


def test_a_retry_is_a_retry_event_before_the_next_request_and_the_run_goes_on(
    tmp_path: Path,
) -> None:
    ran = run(tmp_path, [error_reply(529, "Overloaded", "overloaded_error"), text_reply("ok")])
    (retry,) = ran.of("retry")
    assert (retry["attempt"], retry["reason"], retry["delayMs"]) == (1, "server", 0)
    assert len(ran.fake.requests) == 2
    assert _result(ran)["status"] == "ok"


def test_the_runners_own_failure_is_an_error_result_with_reason_runner(tmp_path: Path) -> None:
    workspace, scratch = _workspace(tmp_path)
    with FakeEndpoint([]) as fake:
        runtime = Runtime.checked(fake.endpoint, MODEL, None)
        service = Service(runtime)
        loop = Loop(
            runtime=runtime,
            options=parse_options(TEST_LIMITS),
            tools=Tools.for_declaration(Declaration(READ_ONLY, workspace, scratch)),
            numbering=EventNumbering(str(uuid.uuid4()), 65536, next_seq=1),
            open=service.stream,
            send=lambda _: None,
            record=lambda _kind, _data: None,
            wait=lambda _: False,
        )
        result = loop.failure("The Anthropic runner failed: RuntimeError: boom").to_data()
        service.close()
    assert (result["status"], result["reason"]) == ("error", "runner")
    assert result["message"] == "The Anthropic runner failed: RuntimeError: boom"


# Requirement: Every run has a turn limit and a token budget (each test sets the limit it checks)


def test_the_turn_limit_carries_out_the_last_replys_calls_then_ends_with_an_error(
    tmp_path: Path,
) -> None:
    script = [tool_reply([(f"t{n}", "Glob", {"pattern": "*"})]) for n in range(4)]
    ran = run(tmp_path, script, options={**TEST_LIMITS, "maxTurns": 3})  # the limit under test
    assert len(ran.fake.requests) == 3
    assert len(ran.of("tool_result")) == 3
    result = _result(ran)
    assert (result["status"], result["reason"]) == ("error", "turn-limit")
    assert "turn limit of 3 was reached" in result["message"]


def test_a_spent_token_budget_carries_out_the_call_then_ends_naming_the_tokens(
    tmp_path: Path,
) -> None:
    script = [tool_reply([GLOB], prompt=1100, completion=100)] * 2
    ran = run(tmp_path, script, options={"maxTurns": 5, "maxTotalTokens": 1000})  # under test
    assert len(ran.fake.requests) == 1
    assert len(ran.of("tool_result")) == 1
    result = _result(ran)
    assert (result["status"], result["reason"]) == ("error", "budget")
    assert "token budget of 1000 was spent" in result["message"]
    assert "1200 tokens" in result["message"]


def test_the_budget_counts_cache_tokens_too(tmp_path: Path) -> None:
    script = [tool_reply([GLOB], prompt=100, completion=100, cache_read=500, cache_write=400)] * 2
    ran = run(tmp_path, script, options={"maxTurns": 5, "maxTotalTokens": 1000})  # under test
    assert len(ran.fake.requests) == 1
    assert "1100 tokens" in _result(ran)["message"]


def test_a_last_reply_past_the_budget_ends_ok_reporting_what_it_used(tmp_path: Path) -> None:
    ran = run(tmp_path, [text_reply("Done.", 900, 300)], {**TEST_LIMITS, "maxTotalTokens": 1000})
    result = _result(ran)
    assert result["status"] == "ok"
    assert result["usage"]["inputTokens"] + result["usage"]["outputTokens"] == 1200


# Requirement: Usage is summed into the result


def test_usage_is_summed_with_cache_reads_counted_apart(tmp_path: Path) -> None:
    script = [
        tool_reply([GLOB], prompt=60, completion=10, cache_read=40, cache_write=None),
        text_reply("ok", prompt=200, completion=20, cache_read=0, cache_write=None),
    ]
    result = _result(run(tmp_path, script))
    assert result["usage"] == {"inputTokens": 260, "cacheReadTokens": 40, "outputTokens": 30}
    assert result["turns"] == 2


def test_cache_writes_reported_by_only_one_reply_give_no_cache_write_count(
    tmp_path: Path,
) -> None:
    script = [
        tool_reply([GLOB], prompt=60, completion=10, cache_read=0, cache_write=50),
        text_reply("ok", prompt=200, completion=20, cache_read=0, cache_write=None),
    ]
    result = _result(run(tmp_path, script))
    assert result["usage"] == {"inputTokens": 260, "cacheReadTokens": 0, "outputTokens": 30}


def test_cache_writes_every_reply_reports_are_summed(tmp_path: Path) -> None:
    script = [
        tool_reply([GLOB], prompt=60, completion=10, cache_read=0, cache_write=50),
        text_reply("ok", prompt=200, completion=20, cache_read=0, cache_write=5),
    ]
    assert _result(run(tmp_path, script))["usage"]["cacheWriteTokens"] == 55


def test_a_reply_without_usage_gives_a_warning_and_a_result_without_usage(tmp_path: Path) -> None:
    bare = Reply(lines=sse([start(used={}), *text_block(0, "ok"), *finish("end_turn")]))
    lines = [
        line.replace(', "usage": {"output_tokens": 5}', "") if isinstance(line, str) else line
        for line in bare.lines or []
    ]
    ran = run(tmp_path, [Reply(lines=lines)])
    (warning,) = ran.of("log")
    assert warning["level"] == "warning"
    assert "reported no usage" in warning["message"]
    assert "usage" not in _result(ran)


# Requirement: Cost is estimated from troupe's price

PRICE = Price(input=1, output=5, cache_read=0.1)
PRICED = [
    tool_reply([GLOB], prompt=60, completion=10, cache_read=40, cache_write=None),
    text_reply("ok", prompt=200, completion=20, cache_read=0, cache_write=None),
]


def test_with_a_price_the_result_has_the_estimate_and_no_cost(tmp_path: Path) -> None:
    result = _result(run(tmp_path, PRICED, price=PRICE))
    assert result["usage"] == {"inputTokens": 260, "cacheReadTokens": 40, "outputTokens": 30}
    assert result["estimatedCostUsd"] == 0.000414
    assert "costUsd" not in result


def test_without_a_price_there_is_neither_cost_nor_estimate(tmp_path: Path) -> None:
    result = _result(run(tmp_path, PRICED))
    assert "estimatedCostUsd" not in result
    assert "costUsd" not in result


# Requirement: A reply's model, when not the runtime's, is a served_model event


def test_another_model_is_one_served_model_before_the_replys_turn(tmp_path: Path) -> None:
    ran = run(tmp_path, [text_reply("ok", model="google/gemma-4-e4b")], model="gemma")
    assert [e["type"] for e in ran.events] == ["served_model", "turn"]
    assert ran.of("served_model")[0]["model"] == "google/gemma-4-e4b"


def test_the_same_other_model_twice_is_one_served_model(tmp_path: Path) -> None:
    script = [tool_reply([GLOB], model="m-2026"), text_reply("ok", model="m-2026")]
    ran = run(tmp_path, script)
    assert [e["model"] for e in ran.of("served_model")] == ["m-2026"]
    assert ran.events[0]["type"] == "served_model"


def test_the_runtimes_own_model_sends_no_served_model(tmp_path: Path) -> None:
    assert run(tmp_path, [text_reply("ok", model=MODEL)]).of("served_model") == []


# Requirement: A context-length refusal ends the run with context-length

PROMPT_TOO_LONG = error_reply(400, "prompt is too long: 210000 tokens > 200000 maximum")
LM_STUDIO_TOO_LONG = stream_error_reply(
    "api_error",
    "The number of tokens to keep from the initial prompt is greater than the context length",
)


@pytest.mark.parametrize("refusal", [PROMPT_TOO_LONG, LM_STUDIO_TOO_LONG], ids=["claude", "lm"])
def test_an_engines_context_refusal_isnt_retried_and_ends_context_length(
    tmp_path: Path, refusal: Reply
) -> None:
    ran = run(tmp_path, [refusal, text_reply("never asked for")])
    assert len(ran.fake.requests) == 1
    assert ran.of("retry") == []
    result = _result(ran)
    assert (result["status"], result["reason"]) == ("error", "context-length")
    assert "longer than the model's context" in result["message"]


# Requirement: A reply made from a cut conversation is never acted on


def test_a_reply_from_a_shrunk_prompt_sends_no_turn_or_call_and_ends_context_length(
    tmp_path: Path,
) -> None:
    script = [
        tool_reply([("t1", "Glob", {"pattern": "*"})], prompt=1000),
        tool_reply([("t2", "Glob", {"pattern": "*"})], prompt=5900),
        tool_reply([("t3", "Glob", {"pattern": "*"})], text="From less.", prompt=4058),
    ]
    ran = run(tmp_path, script)
    assert len(ran.fake.requests) == 3
    assert [e["callId"] for e in ran.of("tool_call")] == ["t1", "t2"]
    assert ran.of("turn") == []
    result = _result(ran)
    assert (result["status"], result["reason"]) == ("error", "context-length")
    assert "answered from less of the conversation than it was sent" in result["message"]


def test_a_conversation_that_grows_goes_on(tmp_path: Path) -> None:
    script = [
        tool_reply([("t1", "Glob", {"pattern": "*"})], prompt=1000),
        tool_reply([("t2", "Glob", {"pattern": "*"})], prompt=5900),
        text_reply("Done.", prompt=6000),
    ]
    assert _result(run(tmp_path, script))["status"] == "ok"


# Requirement: A run stops before the context window the person named


def test_a_reply_reaching_the_window_is_acted_on_then_the_run_ends_context_length(
    tmp_path: Path,
) -> None:
    script = [tool_reply([GLOB], prompt=7900, completion=300), text_reply("never asked for")]
    ran = run(tmp_path, script, options={**TEST_LIMITS, "contextWindow": 8192})  # under test
    assert len(ran.of("tool_result")) == 1
    assert len(ran.fake.requests) == 1
    result = _result(ran)
    assert (result["status"], result["reason"]) == ("error", "context-length")
    assert "8192" in result["message"]


def test_a_reply_whose_prompt_alone_reaches_the_window_isnt_acted_on(tmp_path: Path) -> None:
    script = [tool_reply([GLOB], text="Cut.", prompt=8192, completion=10)]
    ran = run(tmp_path, script, options={**TEST_LIMITS, "contextWindow": 8192})  # under test
    assert ran.of("tool_call") == []
    assert ran.of("turn") == []
    result = _result(ran)
    assert (result["status"], result["reason"]) == ("error", "context-length")
    assert "8192" in result["message"]


def test_without_a_window_a_large_prompt_and_output_go_on(tmp_path: Path) -> None:
    script = [tool_reply([GLOB], prompt=7900, completion=300), text_reply("Done.", prompt=8300)]
    ran = run(tmp_path, script, options={"maxTurns": 5, "maxTotalTokens": 50_000})  # room for both
    assert _result(ran)["status"] == "ok"
    assert len(ran.fake.requests) == 2


# Requirement: A run told compact compacts its conversation and asks again

FILES = {name: f"{name} line\n" * 200 for name in ("a.txt", "b.txt")}
READ_A = ("t1", "Read", {"file_path": "a.txt"})
READ_B = ("t2", "Read", {"file_path": "b.txt"})


def _contents(body: dict[str, Any]) -> dict[str, Any]:
    """Each tool_result's content in a request, by its tool_use_id."""
    return {
        block["tool_use_id"]: block["content"]
        for message in body["messages"]
        if isinstance(message["content"], list)
        for block in message["content"]
        if block["type"] == "tool_result"
    }


def _without_results(body: dict[str, Any]) -> str:
    """A request with every tool_result's content blanked, as bytes compare it."""
    copy = json.loads(json.dumps(body))
    for message in copy["messages"]:
        if isinstance(message["content"], list):
            for block in message["content"]:
                if block["type"] == "tool_result":
                    block["content"] = ""
    return json.dumps(copy, sort_keys=True)


def test_a_refused_request_in_a_run_told_compact_stubs_the_oldest_result_and_asks_again(
    tmp_path: Path,
) -> None:
    ran = run(
        tmp_path,
        [
            tool_reply([READ_A], prompt=1000),
            tool_reply([READ_B], prompt=2000, thinking="Now b."),
            PROMPT_TOO_LONG,
            text_reply("Done.", prompt=1200),
        ],
        compact=True,
        files=FILES,
    )
    assert len(ran.bodies) == 4
    refused, asked_again = ran.bodies[2], ran.bodies[3]
    assert _contents(refused)["t1"] != stub("Read")
    assert _contents(asked_again) == {"t1": stub("Read"), "t2": _contents(refused)["t2"]}
    (context,) = ran.of("context")
    assert (context["kind"], context["by"]) == ("truncated", "runner")
    assert context["messagesBefore"] == context["messagesAfter"] == len(asked_again["messages"])
    result = _result(ran)
    assert result["status"] == "ok"
    assert result["turns"] == 3
    assert result["usage"]["inputTokens"] == 1000 + 2000 + 1200


def test_compaction_leaves_the_system_first_message_assistant_messages_and_latest_results_alone(
    tmp_path: Path,
) -> None:
    ran = run(
        tmp_path,
        [
            tool_reply([READ_A], text="Reading a.", prompt=1000, thinking="First a."),
            tool_reply([READ_B], prompt=2000, thinking="Now b."),
            PROMPT_TOO_LONG,
            text_reply("Done.", prompt=1200),
        ],
        compact=True,
        files=FILES,
        character="You are terse.",
    )
    refused, asked_again = ran.bodies[2], ran.bodies[3]
    assert asked_again["system"] == refused["system"]
    assert asked_again["messages"][0] == refused["messages"][0]
    assistants = [
        (json.dumps(a), json.dumps(b))
        for a, b in zip(refused["messages"], asked_again["messages"], strict=True)
        if a["role"] == "assistant"
    ]
    assert len(assistants) == 2
    assert all(before == after for before, after in assistants)
    assert asked_again["messages"][-1] == refused["messages"][-1]
    assert _without_results(asked_again) == _without_results(refused)


def test_a_shrunk_prompt_in_a_run_told_compact_is_compacted_and_asked_again_within_its_turn(
    tmp_path: Path,
) -> None:
    ran = run(
        tmp_path,
        [
            tool_reply([READ_A], prompt=1000),
            tool_reply([READ_B], prompt=2000),
            text_reply("From less.", prompt=1500),
            text_reply("Done.", prompt=1200),
        ],
        options={**TEST_LIMITS, "maxTurns": 3},  # the shrunk reply mustn't use up a turn
        compact=True,
        files=FILES,
    )
    assert len(ran.bodies) == 4
    assert _contents(ran.bodies[3])["t1"] == stub("Read")
    assert [e["text"] for e in ran.of("turn")] == ["Done."]
    assert len(ran.of("context")) == 1
    assert _result(ran)["status"] == "ok"


def test_a_full_window_in_a_run_told_compact_is_compacted_and_the_run_goes_on(
    tmp_path: Path,
) -> None:
    ran = run(
        tmp_path,
        [
            tool_reply([READ_A], prompt=1000),
            tool_reply([READ_B], prompt=7900, completion=300),
            text_reply("Done.", prompt=4000),
        ],
        options={**TEST_LIMITS, "contextWindow": 8192},  # under test
        compact=True,
        files=FILES,
    )
    assert len(ran.bodies) == 3
    assert _contents(ran.bodies[2])["t1"] == stub("Read")
    assert len(ran.of("context")) == 1
    assert _result(ran)["status"] == "ok"


def test_a_refusal_with_only_the_latest_turns_results_left_ends_context_length(
    tmp_path: Path,
) -> None:
    ran = run(tmp_path, [tool_reply([GLOB]), PROMPT_TOO_LONG], compact=True)
    assert len(ran.bodies) == 2
    assert ran.of("context") == []
    result = _result(ran)
    assert (result["status"], result["reason"]) == ("error", "context-length")
    assert "compaction found nothing more to remove" in result["message"]


def test_a_refusal_in_a_run_told_fail_ends_context_length_without_compacting(
    tmp_path: Path,
) -> None:
    ran = run(tmp_path, [tool_reply([READ_A]), tool_reply([READ_B]), PROMPT_TOO_LONG], files=FILES)
    assert len(ran.bodies) == 3
    assert ran.of("context") == []
    result = _result(ran)
    assert (result["status"], result["reason"]) == ("error", "context-length")
    assert "compaction" not in result["message"]


# Requirement: The transcript is what the library exposes


def test_one_request_and_reply_record_the_params_sent_a_status_note_then_each_event(
    tmp_path: Path,
) -> None:
    ran = run(tmp_path, [text_reply("Done.")])
    kinds = [kind for kind, _ in ran.records]
    assert kinds[:2] == ["sent", "note"]
    assert set(kinds[2:]) == {"received"}
    sent = json.loads(ran.records[0][1])
    assert sent == {k: v for k, v in ran.bodies[0].items() if k != "stream"}
    assert json.loads(ran.records[1][1])["status"] == 200
    events = [json.loads(data)["type"] for _, data in ran.records[2:]]
    assert events[0] == "message_start"
    assert events[-1] == "message_stop"
    assert len(events) == 7


# Requirement: Summaries fit below the event limit


def test_a_long_final_reply_is_cut_to_fit_in_its_turn_and_its_result(tmp_path: Path) -> None:
    ran = run(tmp_path, [text_reply("x" * (1024 * 1024))], event_max_bytes=65536)
    turn = ran.of("turn")[0]
    result = _result(ran)
    for event, key in ((turn, "text"), (result, "message")):
        assert encoded_size(event) <= 65536
        assert event[key].endswith("bytes left out]")


def test_a_long_multibyte_reply_is_cut_on_a_utf8_boundary(tmp_path: Path) -> None:
    ran = run(tmp_path, [text_reply("é" * 100_000)], event_max_bytes=4096)
    for event, key in ((ran.of("turn")[0], "text"), (_result(ran), "message")):
        assert encoded_size(event) <= 4096
        kept = event[key].split(" … [")[0]
        assert set(kept) == {"é"}


# The contract, and stopping


def test_the_events_validate_as_the_contracts_run_events(tmp_path: Path) -> None:
    ran = run(tmp_path, [tool_reply([GLOB], text="look"), text_reply("ok")], price=PRICE)
    check = validator("run-event.schema.json#/$defs/event")
    for event in [*ran.events, _result(ran)]:
        assert check.is_valid(event), event


def test_a_stop_after_one_call_carries_out_none_of_the_rest_and_sends_no_request(
    tmp_path: Path,
) -> None:
    workspace, scratch = _workspace(tmp_path)
    first = ("t1", "Write", {"file_path": "a.txt", "content": "a"})
    second = ("t2", "Write", {"file_path": "b.txt", "content": "b"})
    with FakeEndpoint([tool_reply([first, second]), text_reply("never asked for")]) as fake:
        runtime = Runtime.checked(fake.endpoint, MODEL, None)
        service = Service(runtime)
        loop = Loop(
            runtime=runtime,
            options=parse_options(TEST_LIMITS),
            tools=Tools.for_declaration(Declaration(Effects(write=("*.txt",)), workspace, scratch)),
            numbering=EventNumbering(str(uuid.uuid4()), 65536, next_seq=1),
            open=service.stream,
            send=lambda _: None,
            record=lambda _kind, _data: None,
            wait=lambda _: False,
            stopping=(workspace / "a.txt").exists,
        )
        assert loop.run("Write both.", None) is None
        service.close()
    assert (workspace / "a.txt").exists()
    assert not (workspace / "b.txt").exists()
    assert len(fake.requests) == 1
