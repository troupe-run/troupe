"""Tests for the scripted runner, driven over pipes as troupe drives it (spec: scripted-runner)."""

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from scripted_harness import Session

INIT = {"type": "init", "runner": {"name": "scripted", "version": "0.0.1"}, "tools": ["Write"]}
OK = {"type": "result", "status": "ok", "message": "done"}


@pytest.fixture
def session(tmp_path: Path) -> Iterator[Session]:
    running = Session(tmp_path)
    try:
        yield running
    finally:
        running.kill()


def _events(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [m["params"] for m in messages if m.get("method") == "run/event"]


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


def test_a_second_run_start_is_refused_and_the_first_run_carries_on(session: Session) -> None:
    session.play({"steps": [{"event": INIT}, {"wait": {"ms": 300}}, {"event": OK}]})
    second = session.request(
        "run/start",
        {
            "runId": session.run_id,
            "instructions": "",
            "workspace": str(session.workspace),
            "options": {"script": {"steps": []}},
            "limits": {"eventMaxBytes": 1},
        },
    )
    assert second["error"]["data"]["code"] == "runner.already-started"
    session.notifications(1)
    events = _events(session.received)
    assert [e["type"] for e in events] == ["init", "result"]
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
    assert session.wait() == 0
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
