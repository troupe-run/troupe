"""The scripted runner's tool step: a fake model's call, carried out by the plugin SDK's tools with
the run's declared effects (spec: scripted-runner, "A tool step runs a call through the SDK's
tools", "A tool step can expect an error" and "A write step is still a raw write";
declared-effects design D9)."""

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


def _events(session: Session, count: int) -> list[dict[str, Any]]:
    return [message["params"] for message in session.notifications(count)]


def _tool(name: str, input_: dict[str, Any], **more: Any) -> dict[str, Any]:  # noqa: ANN401
    return {"tool": {"name": name, "input": input_, **more}}


def test_the_init_says_the_runner_checks_each_call(session: Session) -> None:
    session.play({"steps": [{"event": INIT}, {"event": OK}]})
    [init, _] = _events(session, 2)
    assert init["effects"] == "checked"


def test_a_declared_write_through_a_tool_step_writes_and_reports_the_call(
    session: Session,
) -> None:
    step = _tool("Write", {"file_path": "out/a.txt", "content": "hi"}, callId="c1")
    session.play({"steps": [{"event": INIT}, step, {"event": OK}]}, effects={"write": ["out/**"]})
    _, call, result, end = _events(session, 4)
    assert (call["type"], call["seq"], call["callId"], call["tool"]) == (
        "tool_call",
        1,
        "c1",
        "Write",
    )
    assert (result["type"], result["seq"], result["isError"]) == ("tool_result", 2, False)
    assert end["seq"] == 3
    assert (session.workspace / "out" / "a.txt").read_text(encoding="utf-8") == "hi"


def test_a_read_only_actors_write_is_refused_naming_the_write_effect(session: Session) -> None:
    step = _tool("Write", {"file_path": "out/a.txt", "content": "hi"}, isError=True)
    session.play({"steps": [{"event": INIT}, step, {"event": OK}]})
    _, call, result, end = _events(session, 4)
    assert call["callId"] == "tool-1"
    assert result["isError"] is True
    assert "write effect" in result["outputSummary"]
    assert end["status"] == "ok"
    assert not (session.workspace / "out" / "a.txt").exists()


def test_a_result_that_wasnt_expected_ends_the_run_naming_the_step(session: Session) -> None:
    (session.workspace / "a.txt").write_bytes(b"a")
    step = _tool("Delete", {"file_path": "a.txt"}, isError=False)
    session.play({"steps": [{"event": INIT}, step, {"event": OK}]})
    _, _, result, end = _events(session, 4)
    assert result["isError"] is True
    assert end["type"] == "result"
    assert end["status"] == "error"
    assert "tool step 1 (Delete, call tool-1)" in end["message"]
    assert "delete effect" in end["message"]
    assert session.wait() == 0
    assert (session.workspace / "a.txt").exists()


def test_a_tool_step_reaches_the_scratch_directory_without_any_effect(session: Session) -> None:
    scratch = session.scratch()
    step = _tool("Write", {"file_path": str(scratch / "notes.txt"), "content": "n"}, isError=False)
    session.play({"steps": [{"event": INIT}, step, {"event": OK}]})
    _events(session, 4)
    assert (scratch / "notes.txt").read_text(encoding="utf-8") == "n"


@pytest.mark.parametrize(
    ("step", "named"),
    [
        ({"tool": {"name": "Write"}}, "input"),
        ({"tool": {"name": "", "input": {}}}, "name"),
        ({"tool": {"name": "Write", "input": 3}}, "input"),
        ({"tool": {"name": "Write", "input": {}, "isError": "yes"}}, "isError"),
        ({"tool": {"name": "Write", "input": {}, "colour": "red"}}, "colour"),
    ],
)
def test_a_malformed_tool_step_is_refused_naming_its_field(
    session: Session, step: dict[str, Any], named: str
) -> None:
    answer = session.play({"steps": [step]}, valid=False)
    assert named in answer["error"]["data"]["problem"]
