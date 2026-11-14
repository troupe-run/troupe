"""One run's conversation, against the engine stand-in (spec: mistralrs-runner; in-process-runner
design D4, D6 to D9). The conversation runs in this process with a sink that keeps what it sends."""

import json
import uuid
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from mistralrs_harness import validator
from stand_in import StandIn, response
from troupe_plugin_sdk import runner as p
from troupe_plugin_sdk.compaction import stub
from troupe_runner_mistralrs.conversation import Conversation, room
from troupe_runner_mistralrs.defaults import DEFAULT_CONTEXT_LENGTH, TOKEN_MARGIN
from troupe_runner_mistralrs.options import Options, parse_options
from troupe_runner_mistralrs.port import LoadSpec
from troupe_runner_mistralrs.runner import Runner

KV_REFUSAL = "Sequence 1 with 1025 tokens exceeds the total KV cache capacity of 1024 tokens."


class Sink:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.records: list[tuple[str, Any]] = []
        self.stop = False

    def event(self, event: p.RunEvent) -> None:
        data = event.to_data()
        validator("run-event.schema.json#/$defs/event").validate(data)
        self.events.append(data)

    def transcript(self, kind: p.TranscriptKind, record: bytes) -> None:
        self.records.append((kind, json.loads(record)))

    def stopping(self) -> bool:
        return self.stop

    def of(self, type_: str) -> list[dict[str, Any]]:
        return [e for e in self.events if e["type"] == type_]

    @property
    def result(self) -> dict[str, Any]:
        (result,) = self.of("result")
        return result


def _start(
    tmp_path: Path,
    *,
    direction: str = "Do it.",
    character: str | None = None,
    write: list[str] | None = None,
    on_context_full: str = "fail",
    event_max_bytes: int = 65536,
) -> p.RunStartParams:
    workspace, scratch = tmp_path / "w", tmp_path / "s"
    workspace.mkdir(exist_ok=True)
    scratch.mkdir(exist_ok=True)
    data: dict[str, Any] = {
        "runId": str(uuid.uuid4()),
        "direction": direction,
        "workspace": str(workspace),
        "options": {},
        "limits": {"eventMaxBytes": event_max_bytes},
        "effects": {"write": write or [], "delete": [], "move": []},
        "scratch": str(scratch),
        "onContextFull": on_context_full,
        "runtime": {"name": "mistralrs", "model": "/m.gguf", "credential": False},
    }
    if character is not None:
        data["character"] = character
    return p.RunStartParams.from_data(data)


def converse(
    tmp_path: Path,
    script: dict[str, Any],
    *,
    options: dict[str, Any] | None = None,
    load_timeout: float = 30.0,
    **start: Any,  # noqa: ANN401
) -> tuple[Sink, StandIn]:
    stand_in = StandIn(script)
    sink = Sink()
    Conversation(
        start=_start(tmp_path, **start),
        options=parse_options(options or {}),
        model="/m.gguf",
        spec=LoadSpec(Path("/m.gguf")),
        engine_version="0.9.5",
        loader=stand_in.load,
        sink=sink,
        load_timeout=load_timeout,
    ).run()
    return sink, stand_in


def requests(stand_in: StandIn) -> list[Any]:
    (engine,) = stand_in.engines
    return engine.requests


# Requirement: The runner identifies itself as mistralrs


def test_init_names_the_runner_the_engine_and_the_model_then_says_it_loads(tmp_path: Path) -> None:
    sink, _ = converse(tmp_path, {"responses": [response("Hi.")]})
    init, loading = sink.events[0], sink.events[1]
    assert init["type"] == "init"
    assert init["engine"] == {"name": "mistral.rs", "version": "0.9.5", "model": "/m.gguf"}
    assert init["tools"] == ["Read", "Write", "Edit", "Glob", "Grep", "Delete", "Move"]
    assert init["effects"] == "checked"
    assert loading["type"] == "log"
    assert "Loading the model /m.gguf" in loading["message"]


# Requirement: The model loads after the run is acknowledged, within a named limit


def test_a_model_the_engine_wont_load_ends_the_run_with_configuration(tmp_path: Path) -> None:
    words = "cannot find tensor model.language_model.layers.0.linear_attn.dt_bias"
    sink, stand_in = converse(tmp_path, {"load": {"error": words}})
    assert sink.result["status"] == "error"
    assert sink.result["reason"] == "configuration"
    assert words in sink.result["message"]
    assert stand_in.engines == []


def test_a_load_past_its_limit_ends_the_run_with_configuration(tmp_path: Path) -> None:
    sink, _ = converse(tmp_path, {"load": {"sleep": 2}}, load_timeout=0.1)
    assert sink.result["reason"] == "configuration"
    assert "LOAD_TIMEOUT_SECONDS" in sink.result["message"]


# Requirement: The runner always sets the context window


def test_without_a_context_length_the_window_is_the_default(tmp_path: Path) -> None:
    _, stand_in = converse(tmp_path, {"responses": [response("Hi.")]})
    (request,) = requests(stand_in)
    assert request.max_tokens < DEFAULT_CONTEXT_LENGTH
    assert request.max_tokens > DEFAULT_CONTEXT_LENGTH // 2


def test_a_model_with_a_smaller_length_lowers_the_window(tmp_path: Path) -> None:
    _, stand_in = converse(tmp_path, {"maxSequenceLength": 4096, "responses": [response("Hi.")]})
    (request,) = requests(stand_in)
    assert request.max_tokens < 4096


def test_a_context_length_the_model_cant_hold_ends_the_run_with_configuration(
    tmp_path: Path,
) -> None:
    sink, _ = converse(tmp_path, {"maxSequenceLength": 4096}, options={"contextLength": 8192})
    assert sink.result["reason"] == "configuration"
    assert "8192" in sink.result["message"]
    assert "4096" in sink.result["message"]


def test_on_metal_the_window_is_the_engines_kv_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import troupe_runner_mistralrs.runner as runner_module

    loaded: list[LoadSpec] = []
    stand_in = StandIn({})

    def loader(spec: LoadSpec) -> Any:  # noqa: ANN401
        loaded.append(spec)
        return stand_in.load(spec)

    runner = Runner(None, None, None, loader=loader, check=stand_in.check)  # type: ignore[arg-type]
    monkeypatch.setattr(runner_module, "is_metal", lambda: True)
    runner._windowed_loader(8192)(LoadSpec(Path("/m.gguf")))
    monkeypatch.setattr(runner_module, "is_metal", lambda: False)
    runner._windowed_loader(8192)(LoadSpec(Path("/m.gguf")))
    assert [spec.kv_tokens for spec in loaded] == [8192, None]


# Requirement: The character and the direction start the conversation


def test_the_character_then_the_direction_start_the_conversation(tmp_path: Path) -> None:
    _, stand_in = converse(
        tmp_path, {"responses": [response("Hi.")]}, character="You test.", direction="Go."
    )
    assert requests(stand_in)[0].messages == [
        {"role": "system", "content": "You test."},
        {"role": "user", "content": "Go."},
    ]


def test_no_character_means_no_system_message(tmp_path: Path) -> None:
    _, stand_in = converse(tmp_path, {"responses": [response("Hi.")]}, direction="Go.")
    assert requests(stand_in)[0].messages == [{"role": "user", "content": "Go."}]


# Requirement: Every request offers the SDK's tools and nothing of the engine's own


def test_every_request_offers_the_sdks_tools_with_write_naming_the_scratch_directory(
    tmp_path: Path,
) -> None:
    _, stand_in = converse(tmp_path, {"responses": [response("Hi.")]}, options={"think": False})
    (request,) = requests(stand_in)
    names = [tool["function"]["name"] for tool in request.tools]
    assert names == ["Read", "Write", "Edit", "Glob", "Grep", "Delete", "Move"]
    write = next(tool for tool in request.tools if tool["function"]["name"] == "Write")
    assert str(tmp_path / "s") in write["function"]["description"]
    assert request.to_data()["truncate_sequence"] is False
    assert request.think is False


def test_the_real_engine_is_given_none_of_its_own_tools_and_never_truncates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import mistralrs

    from troupe_runner_mistralrs import engine

    built: list[dict[str, Any]] = []
    loaded: list[dict[str, Any]] = []

    def request(**kwargs: Any) -> dict[str, Any]:  # noqa: ANN401
        built.append(kwargs)
        return kwargs

    class FakeRunner:
        def __init__(self, **kwargs: Any) -> None:  # noqa: ANN401
            loaded.append(kwargs)

        def send_chat_completion_request(self, _request: object) -> object:
            raise ValueError("no answer from the fake")

    monkeypatch.setattr(mistralrs, "ChatCompletionRequest", request)
    monkeypatch.setattr(mistralrs, "Runner", FakeRunner)
    model = engine.load(LoadSpec(Path("/models/m.gguf"), seed=7))
    from troupe_runner_mistralrs.port import ChatRequest, EngineFailure

    with pytest.raises(EngineFailure):
        model.chat(ChatRequest([{"role": "user", "content": "hi"}], [], 100))
    (load_args,) = loaded
    assert load_args["token_source"] == "none"  # noqa: S105 - no token: Hugging Face is never asked
    assert load_args["seed"] == 7
    for engine_own in (
        "tool_callbacks",
        "mcp_client_config",
        "code_execution_config",
        "shell_config",
        "search_callback",
        "enable_search",
    ):
        assert engine_own not in load_args
    (request_args,) = built
    assert request_args["truncate_sequence"] is False
    for engine_own in (
        "max_tool_rounds",
        "tool_dispatch_url",
        "enable_code_execution",
        "enable_shell",
        "web_search_options",
    ):
        assert engine_own not in request_args


# Requirement: Each tool call is carried out by the SDK and its result sent back


def test_a_call_the_effects_refuse_is_refused_and_its_refusal_sent_back(tmp_path: Path) -> None:
    (tmp_path / "w").mkdir()
    (tmp_path / "w" / "README.md").write_text("keep me", encoding="utf-8")
    sink, stand_in = converse(
        tmp_path,
        {
            "responses": [
                response(calls=[("c1", "Delete", {"file_path": "README.md"})]),
                response("Couldn't."),
            ]
        },
    )
    assert (tmp_path / "w" / "README.md").exists()
    last = requests(stand_in)[1].messages[-1]
    assert last["role"] == "tool"
    assert last["tool_call_id"] == "c1"
    assert "delete" in last["content"]
    assert sink.result["status"] == "ok"


def test_two_calls_are_carried_out_in_order_each_with_its_result(tmp_path: Path) -> None:
    (tmp_path / "w").mkdir()
    (tmp_path / "w" / "a.txt").write_text("alpha\n", encoding="utf-8")
    sink, stand_in = converse(
        tmp_path,
        {
            "responses": [
                response(
                    calls=[
                        ("r", "Read", {"file_path": "a.txt"}),
                        ("g", "Grep", {"pattern": "alpha"}),
                    ]
                ),
                response("Done."),
            ]
        },
    )
    messages = requests(stand_in)[1].messages
    assert [m.get("tool_call_id") for m in messages[-2:]] == ["r", "g"]
    assert [e["tool"] for e in sink.of("tool_call")] == ["Read", "Grep"]


def test_a_call_with_no_id_gets_one_unique_in_the_run(tmp_path: Path) -> None:
    sink, stand_in = converse(
        tmp_path,
        {"responses": [response(calls=[("", "Glob", {"pattern": "*"})]), response("Done.")]},
    )
    (call,) = sink.of("tool_call")
    assert call["callId"] == "call-1-0"
    assert requests(stand_in)[1].messages[-1]["tool_call_id"] == "call-1-0"


# Requirement: One tool result fits the context window


def test_a_large_file_read_is_capped_to_the_windows_budget(tmp_path: Path) -> None:
    (tmp_path / "w").mkdir()
    (tmp_path / "w" / "big.txt").write_text(
        "".join(f"line {n} {'x' * 90}\n" for n in range(2200)), encoding="utf-8"
    )
    _, stand_in = converse(
        tmp_path,
        {"responses": [response(calls=[("r", "Read", {"file_path": "big.txt"})]), response("ok")]},
        options={"contextLength": 4096},
    )
    content = requests(stand_in)[1].messages[-1]["content"]
    assert len(content.encode()) <= 4096 // 4 * 4
    assert "offset" in content


# Requirement: The loop ends when the model stops calling tools


def test_an_answer_with_no_call_ends_the_run_ok_with_its_text(tmp_path: Path) -> None:
    sink, stand_in = converse(tmp_path, {"responses": [response("All done.")]})
    assert sink.result["status"] == "ok"
    assert sink.result["message"] == "All done."
    assert len(requests(stand_in)) == 1


def test_the_turn_limit_ends_the_run_with_turn_limit(tmp_path: Path) -> None:
    calls = [("c", "Glob", {"pattern": "*"})]
    sink, stand_in = converse(
        tmp_path,
        {"responses": [response(calls=calls), response(calls=calls), response("never")]},
        options={"maxTurns": 2},
    )
    assert sink.result["reason"] == "turn-limit"
    assert "2 turns" in sink.result["message"]
    assert len(requests(stand_in)) == 2


# Requirement: Answers map to turns and tool calls


def test_an_answers_text_is_a_turn_then_its_calls(tmp_path: Path) -> None:
    sink, _ = converse(
        tmp_path,
        {
            "responses": [
                response("Reading it.", calls=[("c", "Glob", {"pattern": "*"})]),
                response("Done."),
            ]
        },
    )
    types = [e["type"] for e in sink.events]
    assert types[2:5] == ["turn", "tool_call", "tool_result"]
    assert sink.events[2]["text"] == "Reading it."


def test_reasoning_is_only_in_the_transcript(tmp_path: Path) -> None:
    sink, _ = converse(tmp_path, {"responses": [response("", reasoning="Let me think.")]})
    assert sink.of("turn") == []
    received = [record for kind, record in sink.records if kind == "received"]
    assert received[0]["choices"][0]["message"]["reasoning_content"] == "Let me think."


# Requirement: The result carries the run's counts


def test_the_result_carries_turns_and_summed_usage_and_no_cost(tmp_path: Path) -> None:
    sink, _ = converse(
        tmp_path,
        {
            "responses": [
                response(calls=[("c", "Glob", {"pattern": "*"})], prompt=186, completion=21),
                response("Done.", prompt=208, completion=16),
            ]
        },
    )
    assert sink.result["turns"] == 2
    assert sink.result["usage"] == {"inputTokens": 394, "outputTokens": 37}
    assert "costUsd" not in sink.result


# Requirement: Each failed run reports its reason


def test_an_engine_error_ends_the_run_with_engine_and_no_retry(tmp_path: Path) -> None:
    sink, stand_in = converse(tmp_path, {"responses": [{"error": "the device went away"}]})
    assert sink.result["reason"] == "engine"
    assert "the device went away" in sink.result["message"]
    assert sink.of("retry") == []
    assert len(requests(stand_in)) == 1


def test_the_runners_own_failure_ends_the_run_with_runner(tmp_path: Path) -> None:
    sink = Sink()
    conversation = Conversation(
        start=_start(tmp_path),
        options=Options(),
        model="/m.gguf",
        spec=LoadSpec(Path("/m.gguf")),
        engine_version="0.9.5",
        loader=StandIn({}).load,
        sink=sink,
    )
    conversation.fail("The mistralrs runner failed: KeyError: 'x'")
    assert sink.result["reason"] == "runner"


# Requirement: Every exchange with the engine is a transcript record


def test_the_transcript_is_each_request_its_additions_and_each_response(tmp_path: Path) -> None:
    sink, _ = converse(
        tmp_path,
        {"responses": [response(calls=[("c", "Glob", {"pattern": "*"})]), response("Done.")]},
    )
    kinds = [kind for kind, _ in sink.records]
    assert kinds == ["sent", "received", "sent", "sent", "sent", "received"]
    first = sink.records[0][1]
    assert first["messages"] == [{"role": "user", "content": "Do it."}]
    assert sink.records[2][1]["role"] == "assistant"
    assert sink.records[3][1]["role"] == "tool"
    assert set(sink.records[4][1]) == {"max_tokens"}
    # The user message, sent with the first request, isn't sent again.
    assert sum(1 for _, r in sink.records if r == {"role": "user", "content": "Do it."}) == 0


# Requirement: Summaries fit below the event limit


def test_a_long_final_answer_fits_the_event_limit(tmp_path: Path) -> None:
    sink, _ = converse(tmp_path, {"responses": [response("x" * 200_000)]})
    assert len(json.dumps(sink.result).encode()) <= 65536
    assert "bytes" in sink.result["message"][-80:]


# Requirement: Each answer is bounded by the room left in the window


def test_a_request_asks_for_at_most_the_room_left(tmp_path: Path) -> None:
    _, stand_in = converse(
        tmp_path, {"responses": [response("ok")]}, options={"contextLength": 8192}
    )
    (request,) = requests(stand_in)
    engine = stand_in.engines[0]
    counted = 8192 - TOKEN_MARGIN - request.max_tokens
    assert counted > 0
    assert request.max_tokens <= 8192 - TOKEN_MARGIN - engine.count("Do it.")


def test_no_room_left_ends_a_run_told_fail_before_any_request(tmp_path: Path) -> None:
    sink, stand_in = converse(
        tmp_path, {"responses": []}, options={"contextLength": 2048}, direction="w " * 5000
    )
    assert sink.result["reason"] == "context-length"
    assert "2048" in sink.result["message"]
    assert "contextLength" in sink.result["message"]
    assert requests(stand_in) == []


@given(st.integers(min_value=2048, max_value=1_048_576), st.integers(min_value=0, max_value=2**21))
def test_an_answer_never_asks_for_more_than_the_room_left(window: int, count: int) -> None:
    assert room(window, count) + count <= window - TOKEN_MARGIN


# Requirement: A run never carries on past its context window


def test_an_answer_that_fills_the_window_is_a_turn_and_ends_with_context_length(
    tmp_path: Path,
) -> None:
    (tmp_path / "w").mkdir()
    sink, stand_in = converse(
        tmp_path,
        {
            "responses": [
                response(
                    "The first part",
                    calls=[("c", "Write", {"file_path": "a.txt"})],
                    finish="length",
                ),
            ]
        },
        write=["**"],
    )
    assert sink.of("turn")[0]["text"] == "The first part"
    assert sink.of("tool_call") == []
    assert not (tmp_path / "w" / "a.txt").exists()
    assert sink.result["reason"] == "context-length"
    assert len(requests(stand_in)) == 1


def test_the_engines_kv_refusal_ends_the_run_with_context_length(tmp_path: Path) -> None:
    sink, _ = converse(tmp_path, {"responses": [{"error": KV_REFUSAL}]})
    assert sink.result["reason"] == "context-length"
    assert KV_REFUSAL.rstrip(".") in sink.result["message"]
    assert sink.of("retry") == []


# Requirement: A run told compact removes old tool results before a request that wouldn't fit


def _reads(n: int, size: int) -> dict[str, Any]:
    calls = [response(calls=[(f"r{i}", "Read", {"file_path": f"f{i}.txt"})]) for i in range(n)]
    return {"responses": [*calls, response("Done.")], "size": size}


def _files(tmp_path: Path, n: int, size: int) -> None:
    (tmp_path / "w").mkdir(exist_ok=True)
    for i in range(n):
        (tmp_path / "w" / f"f{i}.txt").write_text(f"{i}" * size + "\n", encoding="utf-8")


def test_a_run_told_compact_stubs_old_tool_results_and_says_so(tmp_path: Path) -> None:
    _files(tmp_path, 4, 2500)
    sink, stand_in = converse(
        tmp_path, _reads(4, 2500), options={"contextLength": 4096}, on_context_full="compact"
    )
    assert sink.result["status"] == "ok"
    (event, *_) = sink.of("context")
    assert (event["kind"], event["by"]) == ("truncated", "runner")
    last = requests(stand_in)[-1].messages
    assert any(m.get("content") == stub("Read") for m in last)
    assert last[0] == {"role": "user", "content": "Do it."}  # never removed
    assert all(m["role"] != "assistant" or "tool_calls" in m for m in last)
    assert last[-1]["content"] != stub("Read")  # the latest turn's result is kept


def test_a_run_told_fail_changes_no_tool_result_at_the_same_size(tmp_path: Path) -> None:
    _files(tmp_path, 4, 2500)
    sink, stand_in = converse(tmp_path, _reads(4, 2500), options={"contextLength": 4096})
    assert sink.of("context") == []
    assert sink.result["reason"] == "context-length"
    assert all(m.get("content") != stub("Read") for r in requests(stand_in) for m in r.messages)


def test_a_run_told_compact_with_nothing_to_remove_ends_with_context_length(tmp_path: Path) -> None:
    sink, _ = converse(
        tmp_path,
        {"responses": [{"error": KV_REFUSAL}]},
        on_context_full="compact",
    )
    assert sink.of("context") == []
    assert sink.result["reason"] == "context-length"
    assert "nothing more to remove" in sink.result["message"]


# A Rust panic in the engine (PyO3's PanicException, a BaseException) never escapes unreported.


class Panic(BaseException):
    pass


def test_a_panic_in_the_engine_is_an_engine_failure_and_an_exit_is_not(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import mistralrs

    from troupe_runner_mistralrs import engine
    from troupe_runner_mistralrs.port import EngineFailure

    def panics(**kwargs: object) -> None:
        raise Panic("called `Option::unwrap()` on a `None` value")

    monkeypatch.setattr(mistralrs, "Runner", panics)
    with pytest.raises(EngineFailure, match="the engine panicked: Panic"):
        engine.load(LoadSpec(Path("/models/m.gguf")))

    def exits(**kwargs: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(mistralrs, "Runner", exits)
    with pytest.raises(KeyboardInterrupt):
        engine.load(LoadSpec(Path("/models/m.gguf")))


def test_a_load_that_dies_is_configuration_with_its_words_not_the_runners_failure(
    tmp_path: Path,
) -> None:
    def dies(spec: LoadSpec) -> Any:  # noqa: ANN401
        raise Panic("the loader died")

    sink = Sink()
    Conversation(
        start=_start(tmp_path),
        options=Options(),
        model="/m.gguf",
        spec=LoadSpec(Path("/m.gguf")),
        engine_version="0.9.5",
        loader=dies,
        sink=sink,
    ).run()
    assert sink.result["reason"] == "configuration"
    assert "Panic: the loader died" in sink.result["message"]


def test_the_worker_reports_a_panic_as_the_runners_own_failure() -> None:
    reported: list[str] = []

    class Conversing:
        def run(self) -> None:
            raise Panic("boom")

        def fail(self, message: str) -> None:
            reported.append(message)

    stand_in = StandIn({})
    import io

    runner = Runner(
        io.BytesIO(), io.BytesIO(), io.BytesIO(), loader=stand_in.load, check=stand_in.check
    )
    runner._converse(Conversing())  # type: ignore[arg-type]
    assert reported == ["The mistralrs runner failed: Panic: boom"]


def test_a_cut_answer_told_compact_with_nothing_to_remove_is_a_turn_and_a_counted_request(
    tmp_path: Path,
) -> None:
    sink, stand_in = converse(
        tmp_path, {"responses": [response("Once upon", finish="length")]}, on_context_full="compact"
    )
    assert sink.of("turn")[0]["text"] == "Once upon"
    assert sink.result["reason"] == "context-length"
    assert sink.result["turns"] == 1 == len(requests(stand_in))
    assert "nothing more to remove" in sink.result["message"]
    assert "latest turn's" not in sink.result["message"]
