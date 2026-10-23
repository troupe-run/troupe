"""Tests for the scripted runner, driven over pipes as troupe drives it (spec: scripted-runner)."""

import hashlib
import io
import json
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from scripted_harness import Session, validate

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
            "direction": "",
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


# Requirement: A script is a list of steps played in order


def _played_with_everything_queued(
    tmp_path: Path,
    script: dict[str, Any],
    *after_start: dict[str, Any],
    replay_delays: bool = False,
    input_open: bool = False,
) -> tuple[int, list[dict[str, Any]]]:
    """Serve one run in this process with troupe's messages already waiting, including
    ``after_start``, before the runner plays anything: the ordering a loaded machine can produce
    by chance, made certain. With ``input_open``, end of input never comes, so a wait or a
    replay's delays run their full length and the script must end with an ``exit`` step."""
    from troupe_runner_scripted.runner import Runner

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    messages = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersions": [0],
                "host": {"name": "test", "version": "1"},
                "capabilities": [],
            },
        },
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "run/start",
            "params": {
                "runId": "0b9f4c1e-5f7c-4a39-9a43-3d2a3f1d0c11",
                "direction": "test",
                "workspace": str(workspace),
                "options": {"script": script, **({"replayDelays": True} if replay_delays else {})},
                "limits": {"eventMaxBytes": 65536},
            },
        },
        *({"jsonrpc": "2.0", "id": 3 + n, **m} for n, m in enumerate(after_start)),
    ]
    lines = [json.dumps(m).encode() + b"\n" for m in messages]
    stdout = io.BytesIO()
    if not input_open:
        runner = Runner(io.BytesIO(b"".join(lines)), stdout, io.BytesIO())
        runner._read()  # every message is in the inbox before the first step
        code = runner.serve()
    else:
        read_end, write_end = os.pipe()
        with os.fdopen(read_end, "rb") as stdin:
            runner = Runner(stdin, stdout, io.BytesIO())
            for line in lines:  # every message is in the inbox before the first step
                runner._inbox.put(line)
            try:
                code = runner.serve()
            finally:
                os.close(write_end)  # end of input, so the reader thread ends
    return code, [json.loads(line) for line in stdout.getvalue().splitlines()]


def test_steps_after_a_result_play_before_a_waiting_shutdown_is_answered(tmp_path: Path) -> None:
    code, sent = _played_with_everything_queued(
        tmp_path,
        {"steps": [{"event": INIT}, {"event": OK}, {"exit": 3}]},
        {"method": "shutdown", "params": {}},
    )
    assert code == 3
    assert [e["type"] for e in _events(sent)] == ["init", "result"]
    assert not [m for m in sent if m.get("id") == 3], "shutdown was answered"


def test_a_cancel_waiting_during_instant_steps_is_answered_at_the_hang_after_them(
    tmp_path: Path,
) -> None:
    code, sent = _played_with_everything_queued(
        tmp_path,
        {
            "onCancel": "honour",
            "steps": [
                {"event": INIT},
                {"transcript": "one"},
                {"transcript": "two"},
                {"hang": True},
            ],
        },
        {"method": "run/cancel", "params": {"runId": "0b9f4c1e-5f7c-4a39-9a43-3d2a3f1d0c11"}},
    )
    assert code == 0
    played = [m.get("method") for m in sent if "method" in m]
    assert played == ["run/event", "run/transcript", "run/transcript"]
    assert [m for m in sent if m.get("id") == 3] == [{"jsonrpc": "2.0", "id": 3, "result": {}}]


# Requirement: Steps that don't wait play without reading troupe's messages

CANCEL_ANSWER = {"jsonrpc": "2.0", "id": 3, "result": {}}


def _played(sent: list[dict[str, Any]]) -> list[object]:
    """What the runner sent, in order: each notification's method and record, and each answer."""
    return [
        (m["method"], m["params"].get("record")) if "method" in m else m
        for m in sent
        if m.get("id") not in (1, 2)
    ]


def test_a_cancel_waiting_at_a_wait_is_answered_before_the_steps_after_the_wait_play(
    tmp_path: Path,
) -> None:
    code, sent = _played_with_everything_queued(
        tmp_path,
        {
            "onCancel": "ignore",
            "steps": [
                {"event": INIT},
                {"wait": {"ms": 300}},
                {"transcript": "after the wait"},
                {"exit": 0},
            ],
        },
        {"method": "run/cancel", "params": {"runId": "0b9f4c1e-5f7c-4a39-9a43-3d2a3f1d0c11"}},
        input_open=True,
    )
    assert code == 0
    assert _played(sent) == [
        ("run/event", None),
        CANCEL_ANSWER,
        ("run/transcript", "after the wait"),
    ]


def test_a_cancel_waiting_during_a_replays_delay_is_answered_before_the_delayed_record(
    tmp_path: Path,
) -> None:
    recording = tmp_path / "recording.jsonl"
    lines = [
        {"event": {"runId": "11111111-1111-4111-8111-111111111111", **INIT, "seq": 0}, "atMs": 0},
        {"transcript": "delayed", "atMs": 300},
    ]
    recording.write_text("\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8")
    code, sent = _played_with_everything_queued(
        tmp_path,
        {
            "onCancel": "ignore",
            "steps": [
                {"replay": str(recording)},
                {"transcript": "after the replay"},
                {"exit": 0},
            ],
        },
        {"method": "run/cancel", "params": {"runId": "0b9f4c1e-5f7c-4a39-9a43-3d2a3f1d0c11"}},
        replay_delays=True,
        input_open=True,
    )
    assert code == 0
    assert _played(sent) == [
        ("run/event", None),
        CANCEL_ANSWER,
        ("run/transcript", "delayed"),
        ("run/transcript", "after the replay"),
    ]


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
    assert result["status"] == "error"
    assert got in result["message"]
    assert (step.get("hash") or "none") in result["message"]
    assert session.wait() == 0  # and the ok result after it was never sent
    session.validate_all()


def test_a_malformed_character_check_is_refused_as_an_invalid_script(session: Session) -> None:
    answer = session.play({"steps": [{"checkCharacter": {"hash": "md5:abc"}}]}, valid=False)
    assert answer["error"]["data"]["code"] == "scripted.invalid-script"
