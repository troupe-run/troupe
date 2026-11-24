"""Tests for the scripted runner, served in this process with troupe's messages already queued
before it plays a step: steps after a result play before a waiting shutdown is answered, a
waiting cancel is answered at the hang or wait it reaches or before a replay's delayed record,
and a lone surrogate in a message is written as U+FFFD (spec: scripted-runner).

Its tests that start a process, open a socket or use a git theatre are in
integration/test_scripted_runner.py."""

import io
import json
import os
import threading
from pathlib import Path
from typing import Any

from scripted_runner_shared import INIT, OK, _events
from troupe_plugin_sdk import runner as p
from troupe_runner_scripted.runner import Runner

# Requirement: A script is a list of steps played in order

INPUT_OPEN_LIMIT = 30.0
"""How long a run with its input held open may take before the helper closes the input, so a
script that never reaches its exit step fails the test rather than hanging it."""


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
                "effects": {"write": [], "delete": [], "move": []},
                "scratch": str(workspace.parent),
                "onContextFull": "fail",
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
        lock = threading.Lock()
        closed_late: list[bool] = []

        def close_input(late: bool) -> None:
            with lock:
                if not closed_late:
                    closed_late.append(late)
                    os.close(write_end)  # end of input: the runner stops, the reader thread ends

        timer = threading.Timer(INPUT_OPEN_LIMIT, close_input, args=(True,))
        with os.fdopen(read_end, "rb") as stdin:
            runner = Runner(stdin, stdout, io.BytesIO())
            for line in lines:  # every message is in the inbox before the first step
                runner._inbox.put(line)
            timer.start()
            try:
                code = runner.serve()
            finally:
                timer.cancel()
                close_input(False)
        assert closed_late == [False], (
            f"the script didn't reach its exit step within {INPUT_OPEN_LIMIT}s, so its input was "
            f"closed; it sent {stdout.getvalue()!r}"
        )
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


# Requirement: A message's strings are Unicode text (host-robustness design D3)


def test_a_lone_surrogate_in_a_message_is_written_as_the_replacement_character() -> None:
    # An engine's \ud800 escape decodes to a lone surrogate, which the host refuses (#311).
    stdout, stderr = io.BytesIO(), io.BytesIO()
    writer = Runner(io.BytesIO(), stdout, stderr)
    writer._send({"jsonrpc": "2.0", "method": "run/event", "params": {"x\udfff": "a\ud800b"}})
    message = json.loads(stdout.getvalue())
    assert message["params"] == {"x\ufffd": "a\ufffdb"}
    assert p.lone_surrogate(message) is None
    assert b"2 lone surrogates in a run/event message were written as U+FFFD" in stderr.getvalue()
