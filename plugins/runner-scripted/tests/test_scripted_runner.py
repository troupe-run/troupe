"""Tests for the scripted runner, driven over pipes as troupe drives it (spec: scripted-runner).

Its tests that stay in their own process are in unit/test_scripted_runner_unit.py."""

import hashlib
import json
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from scripted_harness import TIMEOUT, Session, validate
from scripted_runner_shared import INIT, OK, _events
from troupe_plugin_sdk import runner as p

POLL_SECONDS = 0.01


@pytest.fixture
def session(tmp_path: Path) -> Iterator[Session]:
    running = Session(tmp_path)
    try:
        yield running
    finally:
        running.kill()


# The contract: handshake, one run, cancel, shutdown, end of input


def test_initialize_answers_version_1_its_name_and_no_capabilities(session: Session) -> None:
    answer = session.initialize()
    assert answer["result"] == {
        "protocolVersion": 0,
        "runner": {"name": "scripted", "version": "0.0.1.dev0"},
        "capabilities": [],
    }
    session.validate_all()


def test_initialize_offering_no_supported_version_is_refused_naming_the_supported_ones(
    session: Session,
) -> None:
    answer = session.request(
        "initialize",
        {"protocolVersions": [7], "host": {"name": "t", "version": "1"}, "capabilities": []},
    )
    assert answer["error"]["data"]["code"] == "runner.unsupported-version"
    assert answer["error"]["data"]["details"] == {"supportedVersions": [0]}
    session.validate_all()


def test_a_request_before_initialize_is_refused(session: Session) -> None:
    answer = session.request("run/cancel", {"runId": session.run_id})
    assert answer["error"]["data"]["code"] == "runner.not-initialized"


def test_a_second_run_start_is_refused_and_the_run_still_ends_with_its_result(
    session: Session,
) -> None:
    # The wait makes it likely the refusal lands mid-run, not certain: the scripted runner has no
    # step that waits for the test, so the name claims only what every run checks (#392; D3).
    session.play({"steps": [{"event": INIT}, {"wait": {"ms": 300}}, {"event": OK}]})
    second = session.request(
        "run/start",
        {
            "runId": session.run_id,
            "direction": "",
            "workspace": str(session.workspace),
            "options": {"script": {"steps": []}},
            "limits": {"eventMaxBytes": 1},
            "effects": {"write": [], "delete": [], "move": []},
            "scratch": str(session.scratch()),
            "onContextFull": "fail",
        },
    )
    assert second["error"]["data"]["code"] == "runner.already-started"
    session.until_result()
    events = _events(session.received)
    assert [e["type"] for e in events] == ["init", "result"]
    assert events[-1]["status"] == "ok"
    session.validate_all()


def test_a_run_told_compact_plays_its_script_unchanged(session: Session) -> None:
    # Requirement: Run start says whether the run may compact (runner-protocol). The scripted
    # runner has no engine and no context, so it accepts onContextFull and ignores it.
    session.play({"steps": [{"event": INIT}, {"event": OK}]}, on_context_full="compact")
    session.until_result()
    events = _events(session.received)
    assert [e["type"] for e in events] == ["init", "result"]
    assert events[-1]["status"] == "ok"
    session.validate_all()


def test_shutdown_after_the_result_is_answered_and_the_runner_exits_0(session: Session) -> None:
    session.play({"steps": [{"event": INIT}, {"event": OK}]})
    session.notifications(2)
    assert session.request("shutdown", {})["result"] == {}
    assert session.wait() == 0
    session.validate_all()


def test_the_runner_exits_when_its_input_closes(session: Session) -> None:
    session.play({"steps": [{"event": INIT}]})
    session.notifications(1)
    session.close_stdin()
    assert session.wait() == 0


def test_an_unknown_method_is_refused(session: Session) -> None:
    session.initialize()
    answer = session.request("run/pause", {})
    assert answer["error"]["code"] == -32601
    assert answer["error"]["data"]["code"] == "runner.unknown-method"
    session.sent.pop()  # run/pause isn't a message the contract lets troupe send
    session.validate_all()


# Requirement: A script is a list of steps played in order


def test_a_script_plays_in_order_with_seq_0_to_3(session: Session) -> None:
    session.play(
        {
            "steps": [
                {"event": INIT},
                {
                    "event": {
                        "type": "tool_call",
                        "callId": "c1",
                        "tool": "Write",
                        "inputSummary": "x",
                    }
                },
                {
                    "event": {
                        "type": "tool_result",
                        "callId": "c1",
                        "isError": False,
                        "outputSummary": "",
                        "outputBytes": 0,
                    }
                },
                {"event": OK},
            ]
        }
    )
    events = _events(session.notifications(4))
    assert [(e["seq"], e["type"]) for e in events] == [
        (0, "init"),
        (1, "tool_call"),
        (2, "tool_result"),
        (3, "result"),
    ]
    assert {e["runId"] for e in events} == {session.run_id}
    session.validate_all()


def test_a_script_is_read_from_the_file_the_options_name(session: Session, tmp_path: Path) -> None:
    path = tmp_path / "script.json"
    path.write_text(json.dumps({"steps": [{"event": INIT}, {"event": OK}]}), encoding="utf-8")
    assert session.start({"scriptPath": str(path)})["result"] == {"runId": session.run_id}
    assert [e["type"] for e in _events(session.notifications(2))] == ["init", "result"]


@pytest.mark.parametrize(
    ("script", "where"),
    [
        ({"steps": [{"dance": True}]}, "unknown step 'dance'"),
        ({"steps": [{"wait": {"ms": 5, "jitter": 1}}]}, "unknown field(s) 'jitter'"),
        ({"steps": [{"event": INIT, "wait": {"ms": 1}}]}, "exactly one key"),
        ({"steps": [], "colour": "red"}, "unknown field(s) 'colour'"),
        ({"steps": [], "onCancel": "maybe"}, "onCancel"),
        ({"steps": [{"exit": -1}]}, "at least 0"),
        # Event steps are checked against the plugin SDK's event types (runner-sdk design D4).
        ({"steps": [{"event": {"type": "result", "status": "ok"}}]}, "missing required field"),
        ({"steps": [{"event": {**OK, "colour": "red"}}]}, "unknown field(s) 'colour'"),
        ({"steps": [{"event": {**OK, "status": "maybe"}}]}, "ResultEvent.status"),
        ({"steps": [{"event": {**OK, "status": "error"}}]}, "an error result needs a reason"),
        ({"steps": [{"event": {**OK, "reason": "budget"}}]}, "an ok result has no reason"),
        (
            {"steps": [{"event": {**OK, "status": "error", "reason": "timeout"}}]},
            "ResultEvent.reason",
        ),
        (
            {
                "steps": [
                    {
                        "event": {
                            **OK,
                            "status": "error",
                            "reason": "quota",
                            "notRetried": "side-effect",
                        }
                    }
                ]
            },
            "notRetried is only on an error result whose reason a retry can name",
        ),
        (
            {"steps": [{"event": {**OK, "notRetried": "side-effect"}}]},
            "an ok result has no notRetried",
        ),
        ({"steps": [{"event": {"type": "dance"}}]}, "unknown event type 'dance'"),
        ({"steps": [{"event": {"type": "oversized"}}]}, "unknown event type 'oversized'"),
    ],
)
def test_an_invalid_script_is_refused_naming_the_step_and_nothing_plays(
    session: Session, script: dict[str, Any], where: str
) -> None:
    answer = session.play(script, valid=False)
    error = answer["error"]["data"]
    assert error["code"] == "scripted.invalid-script"
    assert where in error["problem"]
    session.close_stdin()
    assert session.wait() == 0
    assert session.line() == b""  # nothing was played
    session.validate_all()


@pytest.mark.parametrize("options", [{"script": {"steps": []}, "speed": 2}, {"model": "x"}])
def test_an_unknown_option_is_refused_naming_the_key(
    session: Session, options: dict[str, Any]
) -> None:
    error = session.start(options, valid=False)["error"]["data"]
    assert error["code"] == "scripted.unknown-option"
    assert "'speed'" in error["problem"] or "'model'" in error["problem"]
    session.validate_all()


# Requirement: The runner numbers events itself


def test_a_step_can_override_seq_to_break_the_contract_on_purpose(session: Session) -> None:
    session.play({"steps": [{"event": INIT}, {"event": {**OK, "seq": 5}}]})
    assert [e["seq"] for e in _events(session.notifications(2))] == [0, 5]


def test_a_step_can_send_another_runs_id_on_purpose(session: Session) -> None:
    other = "11111111-1111-4111-8111-111111111111"
    session.play({"steps": [{"event": {**INIT, "runId": other}}]})
    assert [e["runId"] for e in _events(session.notifications(1))] == [other]


# Requirement: Every outcome can be produced on demand


def test_with_cancel_ignored_a_hanging_runner_acknowledges_cancel_and_keeps_running(
    session: Session,
) -> None:
    session.play({"onCancel": "ignore", "steps": [{"event": INIT}, {"hang": True}]})
    session.notifications(1)
    assert session.request("run/cancel", {"runId": session.run_id})["result"] == {}
    with pytest.raises(Exception, match=r"timed out"):
        session.wait(timeout=0.5)
    session.kill()
    session.validate_all()


def test_with_cancel_honoured_the_runner_exits_without_a_result(session: Session) -> None:
    session.play({"steps": [{"event": INIT}, {"hang": True}]})
    session.notifications(1)
    assert session.request("run/cancel", {"runId": session.run_id})["result"] == {}
    assert session.wait() == 0
    assert session.line() == b""
    assert "result" not in [e["type"] for e in _events(session.received)]


def test_with_cancel_honoured_with_a_result_the_runner_reports_an_error_then_exits(
    session: Session,
) -> None:
    session.play({"onCancel": "honour-with-result", "steps": [{"event": INIT}, {"hang": True}]})
    session.notifications(1)
    session.request("run/cancel", {"runId": session.run_id})
    result = session.message()["params"]
    assert (result["type"], result["status"], result["seq"]) == ("result", "error", 1)
    assert result["reason"] == "cancelled"
    assert session.wait() == 0
    session.validate_all()


# Requirement: A script's error result names its reason


def test_a_scripted_error_result_is_sent_with_its_reason(session: Session) -> None:
    quota = {"type": "result", "status": "error", "reason": "quota", "message": "out of credit"}
    session.play({"steps": [{"event": INIT}, {"event": quota}]})
    _, result = _events(session.notifications(2))
    assert (result["status"], result["reason"]) == ("error", "quota")
    session.validate_all()


# Requirement: A script's error result can say it wasn't retried


def test_a_scripted_error_result_is_sent_saying_it_wasnt_retried(session: Session) -> None:
    lost = {
        "type": "result",
        "status": "error",
        "reason": "network",
        "notRetried": "side-effect",
        "message": "the connection dropped after a tool call",
    }
    session.play({"steps": [{"event": INIT}, {"event": lost}]})
    _, result = _events(session.notifications(2))
    assert (result["reason"], result["notRetried"]) == ("network", "side-effect")
    session.validate_all()


def test_an_exit_step_before_any_result_exits_with_its_code(session: Session) -> None:
    session.play({"steps": [{"event": INIT}, {"exit": 3}]})
    session.notifications(1)
    assert session.wait() == 3


def test_raw_stdout_and_stderr_steps_write_exactly_what_they_say(session: Session) -> None:
    session.play({"steps": [{"rawStdout": "not json"}, {"stderr": "diagnostic\n"}, {"exit": 0}]})
    assert session.line() == b"not json\n"
    assert session.wait() == 0
    assert session.stderr() == b"diagnostic\n"


def test_transcript_steps_send_records_with_their_encoding(session: Session) -> None:
    session.play(
        {
            "steps": [
                {"transcript": '{"type":"system"}'},
                {"transcript": {"record": "AAEC", "encoding": "base64"}},
            ]
        }
    )
    first, second = session.notifications(2)
    assert first["params"] == {"runId": session.run_id, "record": '{"type":"system"}'}
    assert second["params"]["encoding"] == "base64"
    session.validate_all()


def test_a_wait_ends_early_when_input_closes(session: Session) -> None:
    session.play({"steps": [{"event": INIT}, {"wait": {"ms": 60_000}}]})
    session.notifications(1)
    session.close_stdin()
    assert session.wait(timeout=10) == 0


# Requirement: The scripted runner exits on end of input


def test_a_hanging_runner_exits_when_its_input_closes_even_with_cancel_ignored(
    session: Session,
) -> None:
    session.play({"onCancel": "ignore", "steps": [{"event": INIT}, {"hang": True}]})
    session.notifications(1)
    session.close_stdin()
    assert session.wait(timeout=10) == 0


# Requirement: Recorded streams replay verbatim


def test_a_recording_replays_its_events_and_transcript_records_in_order(
    session: Session, tmp_path: Path
) -> None:
    recording = tmp_path / "recording.jsonl"
    lines = [
        {"transcript": '{"type":"system","subtype":"init"}', "atMs": 0},
        {"event": {"runId": "11111111-1111-4111-8111-111111111111", **INIT, "seq": 0}},
        {"transcript": '{"type":"result"}'},
        {"event": {"runId": "11111111-1111-4111-8111-111111111111", **OK, "seq": 1}, "atMs": 5},
    ]
    recording.write_text("\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8")
    session.play({"steps": [{"replay": str(recording)}]})
    got = session.notifications(4)
    assert [m["method"] for m in got] == [
        "run/transcript",
        "run/event",
        "run/transcript",
        "run/event",
    ]
    assert got[0]["params"]["record"] == '{"type":"system","subtype":"init"}'
    assert [m["params"]["runId"] for m in got] == [session.run_id] * 4
    assert [m["params"]["seq"] for m in got if m["method"] == "run/event"] == [0, 1]
    session.validate_all()


def test_a_recording_with_an_unknown_field_stops_the_runner_naming_the_line(
    session: Session, tmp_path: Path
) -> None:
    recording = tmp_path / "bad.jsonl"
    recording.write_text('{"transcript": "x", "colour": 1}\n', encoding="utf-8")
    session.play({"steps": [{"replay": str(recording)}]})
    assert session.wait() == 2
    assert b"bad.jsonl:1" in session.stderr()


# writeFile stays inside the workspace


def test_write_file_writes_under_the_workspace(session: Session) -> None:
    session.play(
        {"steps": [{"writeFile": {"path": "out/hello.txt", "content": "hi"}}, {"exit": 0}]}
    )
    assert session.wait() == 0
    assert (session.workspace / "out" / "hello.txt").read_text(encoding="utf-8") == "hi"


@pytest.mark.parametrize(
    "path",
    [
        "/etc/passwd",
        "../outside.txt",
        "out/../../outside.txt",
        "C:\\Windows\\x.txt",
        "C:x.txt",
        "\\\\server\\share\\x.txt",
        "\\rooted.txt",
        "",
    ],
    ids=[
        "posix absolute",
        "parent",
        "nested parent",
        "windows drive",
        "drive relative",
        "unc",
        "windows rooted",
        "empty",
    ],
)
def test_write_file_refuses_every_path_that_could_leave_the_workspace(
    session: Session, path: str
) -> None:
    error = session.play({"steps": [{"writeFile": {"path": path, "content": "x"}}]})["error"]
    assert error["data"]["code"] == "scripted.invalid-script"
    assert "workspace" in error["data"]["problem"]
    assert not (session.workspace.parent / "outside.txt").exists()


# Requirement: An error response's id is null only when the request couldn't be read


def test_a_line_that_isnt_json_is_answered_with_a_parse_error_and_a_null_id(
    session: Session,
) -> None:
    session.send_raw(b"this is not json\n")
    answer = session.message()
    assert answer["error"]["data"]["code"] == "runner.parse-error"
    assert answer["id"] is None
    validate(answer, "error-response.schema.json")


def test_a_refused_request_that_could_be_read_is_answered_with_its_own_id(
    session: Session,
) -> None:
    session.initialize()
    answer = session.request("run/pause", {})
    assert answer["error"]["data"]["code"] == "runner.unknown-method"
    assert answer["id"] == session.sent[-1]["id"]
    validate(answer, "error-response.schema.json")


# Requirement: A script can check the character it received

CHARACTER = "You are the tester."
CHARACTER_HASH = "sha256:" + hashlib.sha256(CHARACTER.encode()).hexdigest()
OTHER_HASH = "sha256:" + "0" * 64


def _check_then(step: dict[str, Any]) -> dict[str, Any]:
    return {"steps": [{"event": INIT}, {"checkCharacter": step}, {"event": OK}]}


def test_a_matching_character_plays_the_next_step(session: Session) -> None:
    session.play(_check_then({"hash": CHARACTER_HASH}), character=CHARACTER)
    events = _events(session.notifications(2))
    assert [e["type"] for e in events] == ["init", "result"]
    assert events[-1]["status"] == "ok"
    session.validate_all()


def test_no_character_matches_a_check_that_there_is_none(session: Session) -> None:
    session.play(_check_then({"absent": True}))
    events = _events(session.notifications(2))
    assert events[-1]["status"] == "ok"


@pytest.mark.parametrize(
    ("step", "character", "got"),
    [
        pytest.param({"hash": OTHER_HASH}, CHARACTER, CHARACTER_HASH, id="a different character"),
        pytest.param({"hash": CHARACTER_HASH}, None, "none", id="no character"),
        pytest.param({"absent": True}, CHARACTER, CHARACTER_HASH, id="a character when none"),
    ],
)
def test_a_character_that_doesnt_match_ends_the_run_with_an_error_naming_both(
    session: Session, step: dict[str, Any], character: str | None, got: str
) -> None:
    session.play(_check_then(step), character=character)
    init, result = _events(session.notifications(2))
    assert init["type"] == "init"
    assert (result["status"], result["reason"]) == ("error", "other")
    assert got in result["message"]
    assert (step.get("hash") or "none") in result["message"]
    assert session.wait() == 0  # and the ok result after it was never sent
    session.validate_all()


def test_a_malformed_character_check_is_refused_as_an_invalid_script(session: Session) -> None:
    answer = session.play({"steps": [{"checkCharacter": {"hash": "md5:abc"}}]}, valid=False)
    assert answer["error"]["data"]["code"] == "scripted.invalid-script"


# Requirement: The scripted runner can use transcript kinds


def test_started_with_transcript_kinds_it_accepts_the_capability_when_offered(
    tmp_path: Path,
) -> None:
    session = Session(tmp_path, args=["--transcript-kinds"])
    try:
        answer = session.initialize(["transcript-kinds"])
        assert answer["result"]["capabilities"] == ["transcript-kinds"]
        session.validate_all()
    finally:
        session.kill()


def test_started_with_transcript_kinds_but_not_offered_it_accepts_no_capability(
    tmp_path: Path,
) -> None:
    session = Session(tmp_path, args=["--transcript-kinds"])
    try:
        assert session.initialize()["result"]["capabilities"] == []
    finally:
        session.kill()


def test_started_without_the_flag_it_accepts_no_capability_even_when_offered(
    session: Session,
) -> None:
    assert session.initialize(["transcript-kinds"])["result"]["capabilities"] == []
    session.validate_all()


def test_a_transcript_step_with_a_kind_is_sent_with_that_kind(session: Session) -> None:
    session.play(
        {
            "steps": [
                {"event": INIT},
                {"transcript": {"record": "data: {}", "kind": "received"}},
                {"event": OK},
            ]
        }
    )
    records = [m["params"] for m in session.notifications(3) if m["method"] == "run/transcript"]
    assert records == [{"runId": session.run_id, "record": "data: {}", "kind": "received"}]
    session.validate_all()


def test_a_transcript_step_of_a_kind_the_contract_doesnt_define_is_refused(
    session: Session,
) -> None:
    script = {"steps": [{"transcript": {"record": "x", "kind": "request"}}]}
    error = session.play(script, valid=False)["error"]["data"]
    assert error["code"] == "scripted.invalid-script"
    assert "steps[0].transcript.kind" in error["problem"]
    assert "not 'request'" in error["problem"]
    session.validate_all()


def test_an_unknown_command_line_argument_stops_the_runner_with_a_usage_message(
    tmp_path: Path,
) -> None:
    session = Session(tmp_path, args=["--kinds"])
    try:
        assert session.wait() == 2
        assert session.process.stderr is not None
        assert (
            b"usage: troupe-runner-scripted [--transcript-kinds]" in session.process.stderr.read()
        )
    finally:
        session.kill()


# The harness itself (request-keeps-notifications design D1, #392)


def _written(session: Session, marker: bytes, within: float) -> bool:
    """Whether the runner has written a line holding ``marker``, waiting up to ``within``
    seconds, without taking anything off the stream the test then reads."""
    deadline = time.monotonic() + within
    while time.monotonic() < deadline:
        if any(marker in line for line in list(session.raw_lines)):
            return True
        time.sleep(POLL_SECONDS)
    return False


def test_a_result_written_before_a_requests_answer_is_still_read_by_until_result(
    session: Session,
) -> None:
    session.play({"steps": [{"event": INIT}, {"event": OK}]})
    assert _written(session, b'"type":"result"', TIMEOUT), "the run never wrote its result"
    second = session.request("run/start", session.sent[-1]["params"])
    messages = session.until_result()
    assert second["error"]["data"]["code"] == "runner.already-started"
    assert messages[-1]["params"]["type"] == "result"


# Requirement: A second initialize is refused (host-robustness design D4, #356)

SECOND_INITIALIZE = {
    "protocolVersions": [0],
    "host": {"name": "test", "version": "1"},
    "capabilities": [],
}
"""A second initialize offering no capabilities."""


def test_a_second_initialize_is_refused_and_the_first_handshakes_kinds_stand(
    tmp_path: Path,
) -> None:
    session = Session(tmp_path, args=["--transcript-kinds"])
    try:
        assert session.initialize(["transcript-kinds"])["result"]["capabilities"] == [
            "transcript-kinds"
        ]
        second = session.request("initialize", SECOND_INITIALIZE)
        assert second["error"]["data"]["code"] == "runner.already-initialized"
        script = {
            "steps": [
                {"event": INIT},
                {"transcript": {"record": "r", "kind": "sent"}},
                {"event": OK},
            ]
        }
        params = {
            "runId": session.run_id,
            "direction": "test",
            "workspace": str(session.workspace),
            "options": {"script": script},
            "limits": {"eventMaxBytes": 65536},
            "effects": {"write": [], "delete": [], "move": []},
            "scratch": str(session.scratch()),
            "onContextFull": "fail",
        }
        assert session.request("run/start", params)["result"] == {"runId": session.run_id}
        records = [
            m["params"] for m in session.until_result() if m.get("method") == "run/transcript"
        ]
        assert records == [{"runId": session.run_id, "record": "r", "kind": "sent"}]
        session.validate_all()
    finally:
        session.kill()


# Requirement: A message's strings are Unicode text: each replacement is recorded
# (host-robustness design D3b)


def _replacement_recorded(events: list[dict[str, Any]]) -> dict[str, Any]:
    """The context event that records a lone surrogate replaced with U+FFFD: just before the first
    event holding U+FFFD, kind other, by runner; ``seq`` gapless; no lone surrogate anywhere
    (host-robustness design D3b)."""
    assert [e["seq"] for e in events] == list(range(len(events)))
    assert all(p.lone_surrogate(e) is None for e in events)
    first = next(i for i, e in enumerate(events) if "\ufffd" in json.dumps(e, ensure_ascii=False))
    context = events[first - 1]
    assert (context["type"], context["kind"], context["by"]) == ("context", "other", "runner")
    assert "wasn't Unicode" in context["message"]
    assert "replaced with U+FFFD" in context["message"]
    return context


def test_a_lone_surrogate_in_a_step_is_recorded_in_a_context_event(session: Session) -> None:
    session.play(
        {
            "steps": [
                {"event": INIT},
                {"event": {"type": "log", "level": "info", "message": "a\ud800b"}},
                {"event": OK},
            ]
        }
    )
    events = [m["params"] for m in session.until_result() if m.get("method") == "run/event"]
    context = _replacement_recorded(events)
    assert "lone surrogate in the log event's message was replaced" in context["message"]
