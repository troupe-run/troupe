"""The LM Studio runner as troupe drives it, against a fake LM Studio (spec: lm-studio-runner)."""

import json
import socket
import time
from pathlib import Path
from typing import Any

import pytest

from fake_lm_studio import (
    Call,
    FakeLMStudio,
    Script,
    listing_fails,
    load_steps,
    model_info,
    models_step,
    predict_step,
    run_script,
    script_of,
)
from lm_studio_harness import MODEL, TEST_LIMITS, Session, events, result, transcript

CANARY = "lm-canary-0123456789"
"""A value no output may hold: what a runtime's credential variable holds in these tests."""


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "notes.txt").write_text("hello from the notes\nsecond line\n", encoding="utf-8")
    return ws


def _run(workspace: Path, fake: FakeLMStudio, **start: Any) -> tuple[Session, list[dict[str, Any]]]:  # noqa: ANN401
    session = Session(workspace)
    answer = session.start(fake.endpoint, **start)
    assert "result" in answer, answer
    messages = session.until_result()
    assert session.shutdown() == 0
    assert fake.mismatches == []
    session.validate_all()
    return session, messages


# Requirement: The runner identifies itself as lm-studio


def test_init_names_the_runner_the_engine_the_model_the_sdks_tools_and_checked_effects(
    workspace: Path,
) -> None:
    with FakeLMStudio(run_script(predict_step("Done."))) as fake:
        _, messages = _run(workspace, fake)
    init = events(messages)[0]
    assert init["type"] == "init"
    assert init["runner"]["name"] == "lm-studio"
    assert init["engine"] == {"name": "lm-studio", "model": MODEL}
    assert init["tools"] == ["Read", "Write", "Edit", "Glob", "Grep", "Delete", "Move"]
    assert init["effects"] == "checked"


# Requirement: Each tool call is carried out by the SDK and checked against the effects
# Requirement: Fixtures pair real LM Studio exchanges with protocol events


def test_the_recorded_two_call_run_reads_then_writes_and_ends_ok(workspace: Path) -> None:
    with FakeLMStudio(script_of("two-calls")) as fake:
        _, messages = _run(
            workspace,
            fake,
            direction="Read notes.txt, then write its first line into out/first.txt.",
            effects={"write": ["out/**"]},
            options={"maxTurns": 6, "maxTotalTokens": 50000},
        )
    run = events(messages)
    calls = [e["tool"] for e in run if e["type"] == "tool_call"]
    assert calls == ["Read", "Write"]
    results = [e for e in run if e["type"] == "tool_result"]
    assert [r["isError"] for r in results] == [False, False]
    assert (workspace / "out" / "first.txt").exists()
    assert result(messages)["status"] == "ok"


def test_a_write_the_actor_didnt_declare_isnt_carried_out_and_is_an_error_result(
    workspace: Path,
) -> None:
    script = run_script(
        predict_step("Writing.", [Call("Write", {"file_path": "out/hello.txt", "content": "hi"})]),
        predict_step("I couldn't write it."),
    )
    with FakeLMStudio(script) as fake:
        _, messages = _run(workspace, fake)
    pair = [e for e in events(messages) if e["type"] in ("tool_call", "tool_result")]
    assert [e["type"] for e in pair] == ["tool_call", "tool_result"]
    assert pair[1]["isError"] is True
    assert "write" in pair[1]["outputSummary"]
    assert not (workspace / "out" / "hello.txt").exists()


# Requirement: The transcript is what the library exposes


def test_the_transcript_holds_the_model_the_chat_each_round_and_each_tool_result_with_kinds(
    workspace: Path,
) -> None:
    script = run_script(
        predict_step("Reading.", [Call("Read", {"file_path": "notes.txt"})]),
        predict_step("Done."),
    )
    with FakeLMStudio(script) as fake:
        _, messages = _run(workspace, fake)
    records = transcript(messages)
    kinds = [r["kind"] for r in records]
    assert kinds == ["received", "sent", "received", "sent", "received"]
    assert json.loads(records[0]["record"])["modelKey"] == MODEL
    sent = json.loads(records[1]["record"])
    assert [t["function"]["name"] for t in sent["tools"]] == [
        "Read",
        "Write",
        "Edit",
        "Glob",
        "Grep",
        "Delete",
        "Move",
    ]
    assert json.loads(records[3]["record"])["role"] == "tool"


def _refused(workspace: Path, endpoint: str | None, **start: Any) -> tuple[Session, dict[str, Any]]:  # noqa: ANN401
    session = Session(workspace)
    answer = session.start(endpoint, **start)
    assert "error" in answer, answer
    session.close_stdin()
    session.wait()
    session.validate_all()
    return session, answer["error"]["data"]


# Requirement: The service comes from the run's runtime


def test_a_run_without_a_runtime_is_refused_naming_how_to_give_one(workspace: Path) -> None:
    _, error = _refused(workspace, None)
    assert error["code"] == "lm-studio.no-runtime"


def test_an_endpoint_in_the_options_is_an_unknown_option(workspace: Path) -> None:
    with FakeLMStudio(run_script()) as fake:
        _, error = _refused(workspace, fake.endpoint, options={"endpoint": "x"}, valid=False)
        assert fake.greetings == 0
    assert error["code"] == "lm-studio.unknown-option"
    assert error["details"] == {"where": "options.endpoint"}


def test_the_runtimes_model_is_the_one_looked_for_and_loaded(workspace: Path) -> None:
    with FakeLMStudio(run_script(predict_step("Done."))) as fake:
        _run(workspace, fake)
        (get,) = fake.sent_on("/llm", "getOrLoad")
    assert get["creationParameter"]["identifier"] == MODEL


# Requirement: An endpoint the library can't use is refused


def test_the_openai_compatible_base_is_refused_and_nothing_is_sent(workspace: Path) -> None:
    with FakeLMStudio(run_script()) as fake:
        _, error = _refused(workspace, fake.endpoint + "/v1")
        assert fake.greetings == 0
    assert error["code"] == "lm-studio.unsupported-endpoint"
    assert fake.endpoint in error["fix"]


# Requirement: A runtime with a credential is refused


def test_a_runtime_with_a_credential_is_refused_and_nothing_is_sent(workspace: Path) -> None:
    token = CANARY
    with FakeLMStudio(run_script()) as fake:
        session = Session(workspace, env={"TROUPE_RUNTIME_CREDENTIAL": token})
        answer = session.start(fake.endpoint, credential=True)
        session.close_stdin()
        assert fake.greetings == 0
    assert answer["error"]["data"]["code"] == "lm-studio.credential-unsupported"
    assert token.encode() not in json.dumps(session.received).encode() + session.stderr()


def test_a_credential_run_start_doesnt_mention_is_a_mismatch(workspace: Path) -> None:
    token = CANARY
    session = Session(workspace, env={"TROUPE_RUNTIME_CREDENTIAL": token})
    answer = session.start("http://127.0.0.1:1234")
    session.close_stdin()
    assert answer["error"]["data"]["code"] == "lm-studio.credential-mismatch"
    assert token.encode() not in json.dumps(session.received).encode() + session.stderr()


# Requirement: The runner checks LM Studio before it acknowledges the run


def test_nothing_listening_is_unreachable_naming_lms_server_start(workspace: Path) -> None:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    _, error = _refused(workspace, f"http://127.0.0.1:{port}")
    assert error["code"] == "lm-studio.unreachable"
    assert "lms server start" in error["fix"]


def test_lm_studio_whose_library_cant_list_models_is_incompatible_naming_the_tested_version(
    workspace: Path,
) -> None:
    script = Script().add("/system", [listing_fails()])
    with FakeLMStudio(script) as fake:
        _, error = _refused(workspace, fake.endpoint)
    assert error["code"] == "lm-studio.incompatible"
    assert "0.4.28" in error["fix"]


def test_a_redirected_greeting_is_refused_and_not_followed(workspace: Path) -> None:
    with FakeLMStudio(Script(greeting="redirect")) as fake:
        _, error = _refused(workspace, fake.endpoint)
    assert error["code"] == "lm-studio.unreachable"
    assert "307" in error["problem"]
    assert "http://192.0.2.1:9/" in error["problem"]


# Requirement: The pre-run check finds a model that can call tools


def test_a_model_that_isnt_downloaded_is_refused_naming_lms_get(workspace: Path) -> None:
    with FakeLMStudio(run_script(models=[model_info(modelKey="other/model")])) as fake:
        _, error = _refused(workspace, fake.endpoint)
    assert error["code"] == "lm-studio.model-not-found"
    assert f"lms get {MODEL}" in error["fix"]


@pytest.mark.parametrize(
    "changes", [{"trainedForToolUse": False}, {"type": "embedding"}], ids=["no-tools", "embedding"]
)
def test_a_model_that_cant_call_tools_is_refused_naming_it(
    workspace: Path, changes: dict[str, Any]
) -> None:
    with FakeLMStudio(run_script(models=[model_info(**changes)])) as fake:
        _, error = _refused(workspace, fake.endpoint)
    assert error["code"] == "lm-studio.model-without-tools"
    assert error["details"] == {"model": MODEL}


# Requirement: The model is loaded with the run's context length, and the length is reported


def test_a_model_not_yet_loaded_is_loaded_with_the_runs_context_length_and_its_load_reported(
    workspace: Path,
) -> None:
    script = run_script(predict_step("Done."), loaded=False, context_length=16384)
    with FakeLMStudio(script) as fake:
        _, messages = _run(workspace, fake, options={**TEST_LIMITS, "contextLength": 16384})
        (get,) = fake.sent_on("/llm", "getOrLoad")
    fields = get["creationParameter"]["loadConfigStack"]["layers"][0]["config"]["fields"]
    assert {"key": "llm.load.contextLength", "value": 16384} in fields
    logs = [e["message"] for e in events(messages) if e["type"] == "log"]
    assert f"LM Studio is loading {MODEL}." in logs
    assert f"LM Studio loaded {MODEL}." in logs


def test_a_model_loaded_with_another_length_is_used_as_it_is_and_the_length_reported(
    workspace: Path,
) -> None:
    script = run_script(predict_step("Done."), context_length=4096)
    with FakeLMStudio(script) as fake:
        _, messages = _run(workspace, fake, options={**TEST_LIMITS, "contextLength": 16384})
    logs = [e["message"] for e in events(messages) if e["type"] == "log"]
    assert any("4096" in log and "16384" in log for log in logs)
    assert not any("loading" in log for log in logs)


# Requirement: The character is the system prompt and the direction the first message


def test_the_character_follows_the_fixed_instructions_and_the_direction_is_the_message(
    workspace: Path,
) -> None:
    with FakeLMStudio(run_script(predict_step("Done."))) as fake:
        _run(workspace, fake, character="You are terse.", direction="Write out/hello.txt")
        (predict,) = fake.sent_on("/llm", "predict")
    system, user = predict["creationParameter"]["history"]["messages"]
    assert system["role"] == "system"
    assert system["content"][0]["text"].endswith("\n\nYou are terse.")
    assert user == {"role": "user", "content": [{"type": "text", "text": "Write out/hello.txt"}]}


# Requirement: Each tool call is carried out by the SDK and checked against the effects


def test_two_calls_in_one_round_are_carried_out_and_reported_in_order(workspace: Path) -> None:
    script = run_script(
        predict_step(
            "",
            [
                Call("Read", {"file_path": "notes.txt"}, "1"),
                Call("Grep", {"pattern": "hello"}, "2"),
            ],
        ),
        predict_step("Done."),
    )
    with FakeLMStudio(script) as fake:
        _, messages = _run(workspace, fake)
    pairs = [
        (e["type"], e.get("tool"))
        for e in events(messages)
        if e["type"] in ("tool_call", "tool_result")
    ]
    assert pairs == [
        ("tool_call", "Read"),
        ("tool_result", None),
        ("tool_call", "Grep"),
        ("tool_result", None),
    ]


# Requirement: A call the library rejects is answered as troupe would answer it


def test_a_call_to_a_tool_that_doesnt_exist_gets_the_sdks_message_and_the_run_goes_on(
    workspace: Path,
) -> None:
    script = run_script(predict_step("", [Call("Bash", {"command": "ls"})]), predict_step("Done."))
    with FakeLMStudio(script) as fake:
        _, messages = _run(workspace, fake)
        second = fake.sent_on("/llm", "predict")[1]
    pair = [e for e in events(messages) if e["type"] in ("tool_call", "tool_result")]
    assert pair[0]["tool"] == "Bash"
    assert pair[1]["isError"] is True
    told = json.dumps(second["creationParameter"]["history"]["messages"][-1])
    assert pair[1]["outputSummary"][:20] in told
    assert result(messages)["status"] == "ok"


def test_a_required_argument_missing_gets_the_sdks_message(workspace: Path) -> None:
    script = run_script(predict_step("", [Call("Read", {})]), predict_step("Done."))
    with FakeLMStudio(script) as fake:
        _, messages = _run(workspace, fake)
    (error,) = [e for e in events(messages) if e["type"] == "tool_result"]
    assert error["isError"] is True
    assert error["outputSummary"] == "Read needs file_path."


# Requirement: Every run has a turn limit and a token budget


def test_the_turn_limit_ends_the_run_whatever_the_last_round_says(workspace: Path) -> None:
    read = Call("Read", {"file_path": "notes.txt"})
    script = run_script(
        predict_step("", [read]), predict_step("", [read]), predict_step("<|tool_call>call:Read{}")
    )
    with FakeLMStudio(script) as fake:
        _, messages = _run(workspace, fake, options={"maxTurns": 3, "maxTotalTokens": 20000})
        rounds = fake.sent_on("/llm", "predict")
    assert len(rounds) == 3
    last_fields = json.dumps(rounds[2]["creationParameter"]["predictionConfigStack"])
    assert (
        "llm.prediction.tools" not in last_fields
        or '"tools": []' in last_fields
        or "toolArray" not in last_fields
    )
    end = result(messages)
    assert (end["status"], end["reason"]) == ("error", "turn-limit")
    assert "turn limit of 3" in end["message"]


def test_the_token_budget_spent_after_a_call_ends_the_run_once_the_call_is_done(
    workspace: Path,
) -> None:
    script = run_script(
        predict_step(
            "", [Call("Read", {"file_path": "notes.txt"})], prompt_tokens=1100, predicted_tokens=100
        ),
        predict_step("never reached"),
    )
    with FakeLMStudio(script) as fake:
        session = Session(workspace)
        session.start(fake.endpoint, options={"maxTurns": 4, "maxTotalTokens": 1000})
        messages = session.until_result()
        session.shutdown()
        assert len(fake.sent_on("/llm", "predict")) == 1
    run = events(messages)
    assert [e["type"] for e in run if e["type"].startswith("tool")] == ["tool_call", "tool_result"]
    end = result(messages)
    assert (end["status"], end["reason"]) == ("error", "budget")
    assert "1000" in end["message"]
    assert "1200" in end["message"]


def test_a_last_reply_past_the_budget_ends_ok(workspace: Path) -> None:
    script = run_script(predict_step("Done.", prompt_tokens=1100, predicted_tokens=100))
    with FakeLMStudio(script) as fake:
        _, messages = _run(workspace, fake, options={"maxTurns": 4, "maxTotalTokens": 1000})
    assert result(messages)["status"] == "ok"


# Requirement: Assistant text is reported as turns


def test_text_before_a_call_is_a_turn_before_it_and_reasoning_is_never_a_turn(
    workspace: Path,
) -> None:
    script = run_script(
        predict_step(
            "Let me read.",
            [Call("Read", {"file_path": "notes.txt"})],
            reasoning="I should read it.",
        ),
        predict_step("It says hello.", reasoning="Now answer."),
    )
    with FakeLMStudio(script) as fake:
        _, messages = _run(workspace, fake)
    kinds = [
        (e["type"], e.get("text")) for e in events(messages) if e["type"] in ("turn", "tool_call")
    ]
    assert kinds == [("turn", "Let me read."), ("tool_call", None), ("turn", "It says hello.")]
    assert "read it" not in json.dumps(events(messages))


# Requirement: A round without a tool call ends the run


def test_a_round_without_a_call_ends_ok_with_its_text(workspace: Path) -> None:
    with FakeLMStudio(script_of("answer-only")) as fake:
        _, messages = _run(
            workspace, fake, direction="Reply with the single word hello. Don't use any tool."
        )
    end = result(messages)
    assert end["status"] == "ok"
    assert end["message"].lower().startswith("hello")


@pytest.mark.parametrize(
    ("stop", "reason"),
    [
        ("contextLengthReached", "context-length"),
        ("maxPredictedTokensReached", "output-limit"),
        ("modelUnloaded", "engine"),
        ("failed", "engine"),
        ("somethingNew", "other"),
    ],
)
def test_a_prediction_stopped_short_ends_with_its_reason(
    workspace: Path, stop: str, reason: str
) -> None:
    with FakeLMStudio(run_script(predict_step("Partial", stop=stop))) as fake:
        _, messages = _run(workspace, fake)
    end = result(messages)
    assert (end["status"], end["reason"]) == ("error", reason)
    if reason == "other":
        assert stop in end["message"]


# Requirement: The result carries the run's counts
# Requirement: A cost is estimated only from run start's price


def test_the_result_sums_each_rounds_tokens_counts_its_rounds_and_reports_no_cost(
    workspace: Path,
) -> None:
    script = run_script(
        predict_step(
            "", [Call("Read", {"file_path": "notes.txt"})], prompt_tokens=1000, predicted_tokens=100
        ),
        predict_step("Done.", prompt_tokens=1300, predicted_tokens=200),
    )
    with FakeLMStudio(script) as fake:
        _, messages = _run(workspace, fake)
    end = result(messages)
    assert end["usage"] == {"inputTokens": 2300, "outputTokens": 300}
    assert end["turns"] == 2
    assert "costUsd" not in end
    assert "estimatedCostUsd" not in end


@pytest.mark.parametrize(
    ("price", "estimate"),
    [({"input": 2, "output": 8}, 6.0), ({"input": 2, "output": 8, "cacheRead": 1}, None)],
    ids=["price", "cache-rate"],
)
def test_a_cost_is_estimated_only_from_run_starts_price(
    workspace: Path, price: dict[str, float], estimate: float | None
) -> None:
    script = run_script(predict_step("Done.", prompt_tokens=1_000_000, predicted_tokens=500_000))
    with FakeLMStudio(script) as fake:
        _, messages = _run(
            workspace, fake, price=price, options={"maxTurns": 2, "maxTotalTokens": 10**8}
        )
    assert result(messages).get("estimatedCostUsd") == estimate


# Requirement: A model other than the run's is reported


def test_a_model_other_than_the_runs_is_reported_once_before_its_turn(workspace: Path) -> None:
    script = run_script(
        predict_step("", [Call("Read", {"file_path": "notes.txt"})], model_key="other/model"),
        predict_step("Done.", model_key="other/model"),
    )
    with FakeLMStudio(script) as fake:
        _, messages = _run(workspace, fake)
    served = [e for e in events(messages) if e["type"] == "served_model"]
    assert [e["model"] for e in served] == ["other/model"]


def test_the_model_asked_for_answering_reports_no_served_model(workspace: Path) -> None:
    with FakeLMStudio(run_script(predict_step("Done."))) as fake:
        _, messages = _run(workspace, fake)
    assert not [e for e in events(messages) if e["type"] == "served_model"]


# Requirement: A connection is retried only before any tool call has run


def test_a_lost_connection_before_any_call_is_retried_once_then_goes_on(workspace: Path) -> None:
    script = run_script(predict_step("Partial answer", drop=2))
    script.add("/system", [models_step()])
    script.add("/llm", [*load_steps(), predict_step("Done.")])
    with FakeLMStudio(script) as fake:
        _, messages = _run(workspace, fake)
    retries = [e for e in events(messages) if e["type"] == "retry"]
    assert len(retries) == 1
    assert retries[0]["reason"] == "network"
    assert result(messages)["status"] == "ok"


def test_a_lost_connection_after_a_call_isnt_retried(workspace: Path) -> None:
    script = run_script(
        predict_step("", [Call("Write", {"file_path": "out/a.txt", "content": "a"})]),
        predict_step("Partial answer", drop=2),
    )
    with FakeLMStudio(script) as fake:
        _, messages = _run(workspace, fake, effects={"write": ["out/**"]})
        assert len(fake.sent_on("/llm", "predict")) == 2
    assert not [e for e in events(messages) if e["type"] == "retry"]
    end = result(messages)
    assert (end["status"], end["reason"]) == ("error", "network")
    assert "run a tool twice" in end["message"]


# Requirement: The transcript is what the library exposes (a host that offers no kinds)


def test_a_host_that_offers_no_kinds_gets_the_records_without_them(workspace: Path) -> None:
    with FakeLMStudio(run_script(predict_step("Done."))) as fake:
        session = Session(workspace, capabilities=[])
        session.start(fake.endpoint)
        messages = session.until_result()
        session.shutdown()
        session.validate_all()
    records = transcript(messages)
    assert records
    assert all("kind" not in r for r in records)


# Requirement: The library's own logging stays out of the run's output


def test_a_run_writes_only_the_contract_to_standard_output_and_nothing_to_standard_error(
    workspace: Path,
) -> None:
    with FakeLMStudio(run_script(predict_step("Done."))) as fake:
        session, _ = _run(workspace, fake)
    assert session.stderr() == b""


# Requirement: Summaries fit below the event limit


def test_a_long_final_message_is_cut_to_fit_the_event_limit(workspace: Path) -> None:
    long = " ".join(["word"] * 40000)
    with FakeLMStudio(run_script(predict_step(long))) as fake:
        _, messages = _run(workspace, fake, event_max_bytes=65536)
    end = result(messages)
    assert len(json.dumps(end).encode()) <= 65536
    assert "left out" in end["message"]


# Requirement: Cancel and end of input stop the run at once


def test_cancel_while_the_model_predicts_stops_it_and_nothing_follows(workspace: Path) -> None:
    slow = predict_step(" ".join(["word"] * 400), pause=0.05)
    with FakeLMStudio(run_script(slow)) as fake:
        session = Session(workspace)
        session.start(fake.endpoint)
        while not any(m.get("params", {}).get("type") == "init" for m in session.received):
            session.message()
        time.sleep(0.5)
        started = time.monotonic()
        answer = session.request("run/cancel", {})
        assert answer["result"] == {}
        assert session.wait() == 0
        assert time.monotonic() - started < 10
        after = session.rest()
    assert after == []


def test_end_of_input_during_a_prediction_stops_the_runner(workspace: Path) -> None:
    slow = predict_step(" ".join(["word"] * 400), pause=0.05)
    with FakeLMStudio(run_script(slow)) as fake:
        session = Session(workspace)
        session.start(fake.endpoint)
        time.sleep(1)
        session.close_stdin()
        assert session.wait() == 0
