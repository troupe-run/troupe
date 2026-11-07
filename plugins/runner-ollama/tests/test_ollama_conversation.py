"""The conversation: troupe's own tool loop over Ollama's /api/chat, against the fake Ollama (spec:
ollama-runner; local-model-runner design D5 to D9, D15).

A recording sink stands in for the runner: it keeps every event and transcript record in the order
they were sent, and doesn't wait out retry delays.
"""

import json
import re
import threading
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from fake_ollama import Answer, FakeOllama, Line, calls, done, final, message, serving, tool_call
from troupe_plugin_sdk import runner as p
from troupe_plugin_sdk.defaults import GLOB_MAX_PATHS, GREP_MAX_MATCHES, READ_MAX_BYTES
from troupe_plugin_sdk.events import encoded_size
from troupe_runner_ollama.client import Client
from troupe_runner_ollama.conversation import (
    NO_TEXT,
    Conversation,
    encode,
    fit_output,
    tool_budget,
    tool_limits,
)
from troupe_runner_ollama.defaults import (
    DEFAULT_CONTEXT_LENGTH,
    READ_NOTE_BYTES,
    RETRY_MAX_ATTEMPTS,
)
from troupe_runner_ollama.options import Options

WINDOW = DEFAULT_CONTEXT_LENGTH


@dataclass
class Recorder:
    """A sink that keeps what it's sent, in order."""

    sent: list[p.RunEvent | bytes] = field(default_factory=list)
    stop: threading.Event = field(default_factory=threading.Event)
    waits: list[float] = field(default_factory=list)

    def event(self, event: p.RunEvent) -> None:
        self.sent.append(event)

    def transcript(self, record: bytes) -> None:
        self.sent.append(record)

    def stopping(self) -> bool:
        return self.stop.is_set()

    def wait(self, seconds: float) -> bool:
        self.waits.append(seconds)
        return self.stop.is_set()

    @property
    def events(self) -> list[p.RunEvent]:
        return [item for item in self.sent if isinstance(item, p.RunEvent)]

    @property
    def records(self) -> list[bytes]:
        return [item for item in self.sent if isinstance(item, bytes)]

    def of(self, kind: type[p.RunEvent]) -> list[Any]:
        return [event for event in self.events if isinstance(event, kind)]

    @property
    def result(self) -> p.ResultEvent:
        (result,) = self.of(p.ResultEvent)
        assert isinstance(result, p.ResultEvent)
        return result


def _start(
    workspace: Path,
    *,
    direction: str = "Write hello.",
    character: str | None = None,
    effects: dict[str, list[str]] | None = None,
    event_max_bytes: int = 65536,
) -> p.RunStartParams:
    scratch = workspace.parent / f"{workspace.name}-scratch"
    scratch.mkdir(exist_ok=True)
    return p.RunStartParams(
        run_id=str(uuid.uuid4()),
        direction=direction,
        workspace=str(workspace),
        options={},
        limits=p.StartLimits(event_max_bytes=event_max_bytes),
        effects=p.EffectsDeclaration(
            write=(effects or {}).get("write", []),
            delete=(effects or {}).get("delete", []),
            move=(effects or {}).get("move", []),
        ),
        scratch=str(scratch),
        character=character,
    )


def _run(
    tmp_path: Path,
    answers: Sequence[Answer],
    *,
    options: Options | None = None,
    window: int = WINDOW,
    idle_timeout: float = 30.0,
    **start: Any,  # noqa: ANN401 - _start's keywords
) -> tuple[Recorder, FakeOllama]:
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    sink = Recorder()
    with serving(answers) as fake:
        Conversation(
            start=_start(workspace, **start),
            options=options or Options(model="fake"),
            window=window,
            engine_version="0.40.14",
            client=Client(fake.url, idle_timeout=idle_timeout),
            sink=sink,
        ).run()
    return sink, fake


def _last_message(fake: FakeOllama, request: int) -> dict[str, Any]:
    last: dict[str, Any] = fake.chats()[request]["messages"][-1]
    return last


# Requirement: The runner identifies itself as ollama


def test_init_names_the_runner_the_engine_the_tools_and_checked_effects(tmp_path: Path) -> None:
    sink, _ = _run(tmp_path, [final("hi")], options=Options(model="qwen3:4b"))
    init = sink.events[0]
    assert isinstance(init, p.InitEvent)
    assert init.seq == 0
    assert init.runner.name == "ollama"
    assert init.engine == p.Engine(name="ollama", version="0.40.14", model="qwen3:4b")
    assert init.tools == ["Read", "Write", "Edit", "Glob", "Grep", "Delete", "Move"]
    assert init.effects == "checked"


# Requirement: The character and the direction start the conversation


def test_an_actor_with_a_character_starts_with_a_system_then_a_user_message(
    tmp_path: Path,
) -> None:
    _, fake = _run(tmp_path, [final("hi")], character="You are terse.", direction="Say hi.")
    assert fake.chats()[0]["messages"] == [
        {"role": "system", "content": "You are terse."},
        {"role": "user", "content": "Say hi."},
    ]


def test_an_actor_with_no_character_starts_with_only_the_user_message(tmp_path: Path) -> None:
    _, fake = _run(tmp_path, [final("hi")], direction="Say hi.")
    assert fake.chats()[0]["messages"] == [{"role": "user", "content": "Say hi."}]


# Requirement: Every request offers the SDK's tools


def test_every_request_offers_the_sdks_seven_tools_naming_the_scratch_directory(
    tmp_path: Path,
) -> None:
    _, fake = _run(tmp_path, [final("hi")])
    tools = fake.chats()[0]["tools"]
    assert [tool["function"]["name"] for tool in tools] == [
        "Read",
        "Write",
        "Edit",
        "Glob",
        "Grep",
        "Delete",
        "Move",
    ]
    assert all(tool["type"] == "function" for tool in tools)
    assert all(tool["function"]["parameters"]["additionalProperties"] is False for tool in tools)
    write = next(tool for tool in tools if tool["function"]["name"] == "Write")
    assert "workspace-scratch" in write["function"]["description"]


def test_the_options_become_ollamas_own_fields_and_nothing_else_is_sent(tmp_path: Path) -> None:
    options = Options(model="fake", temperature=0.0, seed=7, think="low")
    _, fake = _run(tmp_path, [final("hi")], options=options, window=32768)
    body = fake.chats()[0]
    assert body["options"] == {"num_ctx": 32768, "temperature": 0.0, "seed": 7}
    assert body["think"] == "low"
    assert body["stream"] is True
    assert set(body) == {
        "model",
        "messages",
        "tools",
        "stream",
        "truncate",
        "shift",
        "options",
        "think",
    }


def test_unset_options_are_left_to_ollama_but_the_window_never_is(tmp_path: Path) -> None:
    _, fake = _run(tmp_path, [final("hi")])
    body = fake.chats()[0]
    assert body["options"] == {"num_ctx": WINDOW}
    assert "think" not in body


# Requirement: A run never carries on past its context window


def test_every_request_asks_ollama_not_to_cut_the_conversation(tmp_path: Path) -> None:
    _, fake = _run(tmp_path, [calls(tool_call("Glob", {"pattern": "*"})), final("done")])
    assert len(fake.chats()) == 2
    assert all(body["truncate"] is False and body["shift"] is False for body in fake.chats())


def test_a_request_ollama_refuses_ends_the_run_naming_the_window_and_context_length(
    tmp_path: Path,
) -> None:
    refusal = (
        b'{"error":"request (3031 tokens) exceeds the available context size (512 tokens), '
        b'try increasing it"}'
    )
    sink, fake = _run(
        tmp_path,
        [calls(tool_call("Glob", {"pattern": "*"})), Answer(status=400, body=refusal)],
        window=512,
    )
    assert len(fake.chats()) == 2
    assert sink.result.status == "error"
    assert "exceeds the available context size" in sink.result.message
    assert "context window is 512 tokens" in sink.result.message
    assert "contextLength" in sink.result.message
    assert sink.of(p.RetryEvent) == []
    assert refusal in sink.records


def test_a_cut_answer_is_a_warning_and_the_run_goes_on(tmp_path: Path) -> None:
    sink, _ = _run(tmp_path, [Answer([message("partial"), done(reason="length")])])
    (log,) = sink.of(p.LogEvent)
    assert log.level == "warning"
    assert "output limit" in log.message
    assert sink.result.status == "ok"


# Requirement: An answer's other model is a served_model event
# Built, not recorded: every recording's answers echo the model asked for.


def _named(model: str, answer: Answer) -> Answer:
    return Answer(answer.lines, model=model)


def test_an_answer_under_another_name_sends_served_model_before_its_turn(tmp_path: Path) -> None:
    sink, _ = _run(tmp_path, [_named("qwen3:0.6b-q4", final("hi"))])
    assert [e.TYPE for e in sink.events] == ["init", "served_model", "turn", "result"]
    (served,) = sink.of(p.ServedModelEvent)
    assert served.model == "qwen3:0.6b-q4"


def test_two_answers_from_the_same_other_model_send_one_served_model(tmp_path: Path) -> None:
    glob = calls(tool_call("Glob", {"pattern": "*"}))
    sink, _ = _run(tmp_path, [_named("other", glob), _named("other", final("hi"))])
    assert [s.model for s in sink.of(p.ServedModelEvent)] == ["other"]


def test_answers_echoing_the_model_asked_for_send_no_served_model(tmp_path: Path) -> None:
    sink, _ = _run(tmp_path, [final("hi")])
    assert sink.of(p.ServedModelEvent) == []


# Requirement: One tool result fits the context window


def test_the_tool_limits_follow_the_window_and_never_pass_the_sdks_defaults() -> None:
    default = tool_limits(WINDOW)
    assert default.read_max_bytes == tool_budget(WINDOW) - READ_NOTE_BYTES
    assert default.read_max_bytes < READ_MAX_BYTES
    small, large = tool_limits(8192), tool_limits(32768)
    assert small.read_max_bytes < default.read_max_bytes < large.read_max_bytes
    assert small.grep_max_matches < large.grep_max_matches
    huge = tool_limits(10_000_000)
    assert huge.read_max_bytes == READ_MAX_BYTES
    assert huge.glob_max_paths == GLOB_MAX_PATHS
    assert huge.grep_max_matches == GREP_MAX_MATCHES


@pytest.mark.parametrize("window", [8192, WINDOW, 32768])
def test_a_large_file_read_fits_the_budget_keeping_the_sdks_note_on_where_to_read_on(
    tmp_path: Path, window: int
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "big.txt").write_text(
        "".join(f"line {n} {'x' * 90}\n" for n in range(2000)), encoding="utf-8"
    )
    sink, fake = _run(
        tmp_path, [calls(tool_call("Read", {"file_path": "big.txt"})), final("ok")], window=window
    )
    content = _last_message(fake, 1)["content"]
    assert len(content.encode("utf-8")) <= tool_budget(window)
    # The SDK's own note, naming the line to read on from, not fit_output's generic one.
    assert re.search(r"\[Stopped before line (\d+) of 2000: read on with offset \1\.\]", content)
    assert "cut to" not in content
    assert sink.result.status == "ok"


def test_a_search_over_very_long_lines_is_cut_with_a_note(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    for n in range(20):
        (workspace / f"f{n}.txt").write_text("needle " + "y" * 5000 + "\n", encoding="utf-8")
    _, fake = _run(
        tmp_path, [calls(tool_call("Grep", {"pattern": "needle"})), final("ok")], window=4096
    )
    content = _last_message(fake, 1)["content"]
    assert len(content.encode("utf-8")) <= tool_budget(4096)
    assert content.endswith(
        "[cut to 3072 bytes to fit the model's context window; narrow it with path or glob, "
        "or read with offset and limit]"
    )


# Requirement: Each tool call is carried out by the SDK and its result sent back


def test_a_write_the_effects_allow_is_carried_out_and_its_output_sent_back(tmp_path: Path) -> None:
    sink, fake = _run(
        tmp_path,
        [calls(tool_call("Write", {"file_path": "out/a.txt", "content": "hello"})), final("done")],
        effects={"write": ["out/**"]},
    )
    assert (tmp_path / "workspace" / "out" / "a.txt").read_text(encoding="utf-8") == "hello"
    (result,) = sink.of(p.ToolResultEvent)
    assert result.is_error is False
    last = _last_message(fake, 1)
    assert last["role"] == "tool"
    assert last["tool_name"] == "Write"
    assert "out/a.txt" in last["content"]


def test_a_call_the_effects_refuse_changes_nothing_and_its_refusal_is_sent_back(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "README.md").write_text("keep", encoding="utf-8")
    sink, fake = _run(
        tmp_path, [calls(tool_call("Delete", {"file_path": "README.md"})), final("sorry")]
    )
    assert (workspace / "README.md").exists()
    (result,) = sink.of(p.ToolResultEvent)
    assert result.is_error is True
    last = _last_message(fake, 1)
    assert last["tool_name"] == "Delete"
    assert "delete" in last["content"]


def test_two_calls_in_one_answer_run_in_order_each_with_its_own_id(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "a.py").write_text("def main(): pass\n", encoding="utf-8")
    sink, fake = _run(
        tmp_path,
        [
            calls(
                tool_call("Read", {"file_path": "a.py"}, 0),
                tool_call("Grep", {"pattern": "def main"}, 1),
            ),
            final("done"),
        ],
    )
    tool_calls = sink.of(p.ToolCallEvent)
    assert [call.tool for call in tool_calls] == ["Read", "Grep"]
    assert [call.call_id for call in tool_calls] == ["call-1-0", "call-1-1"]
    messages = fake.chats()[1]["messages"]
    assert [m.get("tool_name") for m in messages[-2:]] == ["Read", "Grep"]


def test_a_call_with_an_id_keeps_it(tmp_path: Path) -> None:
    call = {**tool_call("Glob", {"pattern": "*"}), "id": "abc"}
    sink, _ = _run(tmp_path, [calls(call), final("done")])
    assert [event.call_id for event in sink.of(p.ToolCallEvent)] == ["abc"]


def test_a_call_with_no_name_is_an_unknown_tool_and_text_arguments_are_parsed(
    tmp_path: Path,
) -> None:
    sink, fake = _run(
        tmp_path,
        [
            calls(
                {"function": {"arguments": {}}},
                tool_call("Glob", '{"pattern": "*"}', 1),
                tool_call("Glob", ["*"], 2),
            ),
            final("done"),
        ],
    )
    results = sink.of(p.ToolResultEvent)
    assert [result.is_error for result in results] == [True, False, True]
    assert "no tool named" in fake.chats()[1]["messages"][-3]["content"]


# Requirement: The loop ends when the model stops calling tools


def test_an_answer_with_no_tool_call_ends_the_run_ok_with_its_text(tmp_path: Path) -> None:
    sink, fake = _run(tmp_path, [final("All done.")])
    assert sink.result.status == "ok"
    assert sink.result.message == "All done."
    assert len(fake.chats()) == 1


def test_an_empty_final_answer_says_it_had_no_text(tmp_path: Path) -> None:
    sink, _ = _run(tmp_path, [final("")])
    assert sink.result.message == NO_TEXT
    assert sink.of(p.TurnEvent) == []


def test_the_turn_limit_ends_the_run_with_an_error_and_no_further_request(tmp_path: Path) -> None:
    glob = calls(tool_call("Glob", {"pattern": "*"}))
    sink, fake = _run(tmp_path, [glob, glob, glob], options=Options(model="fake", max_turns=2))
    assert len(fake.chats()) == 2
    assert len(sink.of(p.ToolCallEvent)) == 2
    assert sink.result.status == "error"
    assert "stopped after 2 turns (maxTurns)" in sink.result.message


# Requirement: Answers map to turns and tool calls


def test_an_answers_streamed_text_is_one_turn_before_its_calls(tmp_path: Path) -> None:
    answer = Answer(
        [
            message("Read"),
            message("ing "),
            message("it.", tool_calls=[tool_call("Glob", {"pattern": "*"})]),
            done(),
        ]
    )
    sink, _ = _run(tmp_path, [answer, final("done")])
    kinds = [type(event).__name__ for event in sink.events]
    assert kinds[:4] == ["InitEvent", "TurnEvent", "ToolCallEvent", "ToolResultEvent"]
    turn = sink.of(p.TurnEvent)[0]
    assert (turn.role, turn.text) == ("assistant", "Reading it.")


def test_thinking_is_kept_in_the_transcript_only(tmp_path: Path) -> None:
    answer = Answer([message("", thinking="Let me think."), message("Hi."), done()])
    sink, _ = _run(tmp_path, [answer])
    assert [turn.text for turn in sink.of(p.TurnEvent)] == ["Hi."]
    assert any(b"Let me think." in record for record in sink.records)
    assert all("think" not in json.dumps(event.to_data()) for event in sink.events)


def test_thinking_goes_back_to_ollama_with_the_calls_it_led_to(tmp_path: Path) -> None:
    answer = Answer(
        [
            message(
                "", thinking="I'll list files.", tool_calls=[tool_call("Glob", {"pattern": "*"})]
            ),
            done(),
        ]
    )
    _, fake = _run(tmp_path, [answer, final("done")])
    assistant = fake.chats()[1]["messages"][-2]
    assert assistant["role"] == "assistant"
    assert assistant["thinking"] == "I'll list files."
    assert assistant["tool_calls"] == [tool_call("Glob", {"pattern": "*"})]


# Requirement: The result carries the run's counts


def test_the_result_sums_each_answers_counts_and_carries_no_cost(tmp_path: Path) -> None:
    sink, _ = _run(
        tmp_path,
        [
            calls(tool_call("Glob", {"pattern": "*"}), prompt=120, generated=40),
            final("ok", 300, 25),
        ],
    )
    result = sink.result
    assert result.turns == 2
    assert result.usage == p.Usage(input_tokens=420, output_tokens=65)
    assert result.cost_usd is None
    assert result.duration_ms is not None


def test_a_counter_no_answer_reported_is_left_out(tmp_path: Path) -> None:
    sink, _ = _run(tmp_path, [Answer([message("ok"), done(prompt=None, generated=7)])])
    assert sink.result.usage == p.Usage(output_tokens=7)


# Requirement: Ollama's errors end the run as error results


def test_a_server_error_that_lasts_ends_the_run_with_ollamas_message(tmp_path: Path) -> None:
    failed = Answer(status=500, body=b'{"error": "model failed to load"}')
    sink, fake = _run(tmp_path, [failed] * RETRY_MAX_ATTEMPTS)
    assert len(fake.chats()) == RETRY_MAX_ATTEMPTS
    assert [r.attempt for r in sink.of(p.RetryEvent)] == list(range(1, RETRY_MAX_ATTEMPTS))
    assert sink.result.status == "error"
    assert "model failed to load" in sink.result.message


def test_an_error_part_way_through_a_stream_ends_the_run_at_once(tmp_path: Path) -> None:
    answer = Answer([message("Hel"), {"error": "an error was encountered while running the model"}])
    sink, fake = _run(tmp_path, [answer])
    assert len(fake.chats()) == 1
    assert sink.of(p.RetryEvent) == []
    assert sink.result.status == "error"
    assert "an error was encountered while running the model" in sink.result.message


def test_a_request_ollama_refuses_isnt_retried(tmp_path: Path) -> None:
    sink, fake = _run(tmp_path, [Answer(status=400, body=b'{"error": "invalid"}'), final("x")])
    assert len(fake.chats()) == 1
    assert sink.of(p.RetryEvent) == []
    assert sink.result.status == "error"


# Requirement: Connection failures and server errors are retried and reported


def test_a_dropped_connection_is_a_network_retry_and_the_run_goes_on(tmp_path: Path) -> None:
    dropped = Answer([message("a"), message("b"), done()], close_after=1)
    sink, fake = _run(tmp_path, [dropped, final("ok")])
    (retry,) = sink.of(p.RetryEvent)
    assert (retry.reason, retry.attempt, retry.max_attempts) == ("network", 1, RETRY_MAX_ATTEMPTS)
    assert sink.result.status == "ok"
    assert len(fake.chats()) == 2
    assert fake.chat_bodies()[0] == fake.chat_bodies()[1]


def test_a_busy_server_is_two_server_retries_then_the_answer(tmp_path: Path) -> None:
    busy = Answer(status=503, body=b'{"error": "server busy"}')
    sink, _ = _run(tmp_path, [busy, busy, final("ok")])
    retries = sink.of(p.RetryEvent)
    assert [(r.reason, r.attempt) for r in retries] == [("server", 1), ("server", 2)]
    assert [r.delay_ms for r in retries] == [1000, 2000]
    assert sink.result.status == "ok"


def test_retries_spent_end_the_run_naming_the_status(tmp_path: Path) -> None:
    # Ollama's own body for a busy server, as the server-retries fixture holds it.
    busy = Answer(
        status=503,
        body=b'{"error":"server busy, please try again.  maximum pending requests exceeded"}',
    )
    sink, _ = _run(tmp_path, [busy] * RETRY_MAX_ATTEMPTS)
    assert len(sink.of(p.RetryEvent)) == RETRY_MAX_ATTEMPTS - 1
    assert "status 503: server busy" in sink.result.message
    assert sink.result.status == "error"


def test_a_silent_stream_is_a_network_retry(tmp_path: Path) -> None:
    silent = Answer([message("a")], silent=True)
    sink, _ = _run(tmp_path, [silent, final("ok")], idle_timeout=0.3)
    (retry,) = sink.of(p.RetryEvent)
    assert retry.reason == "network"
    assert sink.result.status == "ok"


def test_a_line_that_isnt_json_is_a_network_retry(tmp_path: Path) -> None:
    sink, _ = _run(tmp_path, [Answer([b"<html>proxy error</html>"]), final("ok")])
    (retry,) = sink.of(p.RetryEvent)
    assert retry.reason == "network"
    assert b"<html>proxy error</html>" in sink.records


# Requirement: Every exchange with Ollama is a transcript record


def test_a_run_with_one_tool_call_records_each_exchange_in_order(tmp_path: Path) -> None:
    first = calls(tool_call("Glob", {"pattern": "*"}))
    second = final("done")
    sink, fake = _run(tmp_path, [first, second])
    bodies = fake.chat_bodies()
    first_lines = [line.data for line in first.encoded()]
    second_lines = [line.data for line in second.encoded()]
    assistant, tool = sink.records[1 + len(first_lines) : 3 + len(first_lines)]
    assert sink.records == [bodies[0], *first_lines, assistant, tool, *second_lines]
    assert json.loads(assistant)["role"] == "assistant"
    assert json.loads(tool)["role"] == "tool"


def test_each_added_message_is_recorded_exactly_as_it_is_sent(tmp_path: Path) -> None:
    sink, fake = _run(
        tmp_path,
        [calls(tool_call("Write", {"file_path": "é.txt", "content": "ü\n"})), final("done")],
        effects={"write": ["**"]},
    )
    later = fake.chat_bodies()[1]
    added = [r for r in sink.records if r.startswith(b'{"role"')]
    assert len(added) == 2
    assert all(record in later for record in added)


def test_history_sent_again_is_recorded_once(tmp_path: Path) -> None:
    glob = calls(tool_call("Glob", {"pattern": "*"}))
    sink, fake = _run(tmp_path, [glob, glob, final("done")], direction="the direction")
    assert len(fake.chats()) == 3
    assert sum(record.count(b"the direction") for record in sink.records) == 1


def test_a_record_that_leads_to_an_event_comes_before_it(tmp_path: Path) -> None:
    sink, _ = _run(tmp_path, [final("hello")])
    final_line = next(
        index
        for index, item in enumerate(sink.sent)
        if isinstance(item, bytes) and json.loads(item).get("done") is True
    )
    turn = next(index for index, item in enumerate(sink.sent) if isinstance(item, p.TurnEvent))
    assert final_line < turn


def test_a_line_that_isnt_utf8_reaches_the_sink_verbatim(tmp_path: Path) -> None:
    raw = b"\xff\xfe not text"
    sink, _ = _run(tmp_path, [Answer([raw]), final("ok")])
    assert raw in sink.records


# Requirement: Summaries fit below the event limit


def test_a_long_final_answer_fits_the_event_limit_saying_what_was_left_out(tmp_path: Path) -> None:
    sink, _ = _run(tmp_path, [final("x" * 200_000)], event_max_bytes=65536)
    result = sink.result
    assert encoded_size(result.to_data()) <= 65536
    assert result.message.endswith("bytes left out]")
    assert all(encoded_size(event.to_data()) <= 65536 for event in sink.events)


# Stopping (design D3)


def test_a_run_that_starts_stopping_sends_nothing_more(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    sink = Recorder()
    slow = Answer([message("a"), Line(b"{}", delay=30)])
    with serving([slow]) as fake:
        client = Client(fake.url)
        conversation = Conversation(
            start=_start(workspace),
            options=Options(model="fake"),
            window=WINDOW,
            engine_version="0.40.14",
            client=client,
            sink=sink,
        )
        worker = threading.Thread(target=conversation.run)
        worker.start()
        assert fake.closed_by_client.wait(0) is False
        while not sink.records[1:]:
            threading.Event().wait(0.01)
        sink.stop.set()
        client.close()
        worker.join(5)
        assert not worker.is_alive()
        assert fake.closed_by_client.wait(5)
    assert sink.of(p.ResultEvent) == []


def test_encode_is_compact_utf8() -> None:
    assert encode({"a": "é", "b": [1, 2]}) == '{"a":"é","b":[1,2]}'.encode()


# Found by a review of the code (troupe-run/troupe#283).


def test_fail_before_the_result_sends_a_log_error_then_an_error_result(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    sink = Recorder()
    with serving([]) as fake:
        conversation = Conversation(
            start=_start(workspace),
            options=Options(model="fake"),
            window=WINDOW,
            engine_version="0.40.14",
            client=Client(fake.url),
            sink=sink,
        )
        conversation.fail("The Ollama runner failed: KeyError: 'boom'")
    (log,) = sink.of(p.LogEvent)
    assert (log.level, log.message) == ("error", "The Ollama runner failed: KeyError: 'boom'")
    assert sink.result.status == "error"
    assert [event.seq for event in sink.events] == [0, 1]


def test_fail_after_the_result_sends_only_the_log_error(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    sink = Recorder()
    with serving([final("done")]) as fake:
        conversation = Conversation(
            start=_start(workspace),
            options=Options(model="fake"),
            window=WINDOW,
            engine_version="0.40.14",
            client=Client(fake.url),
            sink=sink,
        )
        conversation.run()
        conversation.fail("late")
    assert [type(event).__name__ for event in sink.events][-2:] == ["ResultEvent", "LogEvent"]
    assert len(sink.of(p.ResultEvent)) == 1


def test_fit_output_stays_within_a_budget_smaller_than_its_note() -> None:
    assert len(fit_output("x" * 500, 40).encode("utf-8")) <= 40
    assert fit_output("short", 40) == "short"
