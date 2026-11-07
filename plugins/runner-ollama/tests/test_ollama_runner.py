"""The Ollama runner as troupe sees it: a process speaking the runner contract, against the fake
Ollama (spec: ollama-runner, runner-protocol; local-model-runner design D3, D4, D16).

Every test checks every message either side sent against the contract, with the runner's schemas
bound.
"""

import io
import json
import socket
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from fake_ollama import (
    Answer,
    FakeOllama,
    Line,
    Settings,
    calls,
    done,
    final,
    message,
    serving,
    tool_call,
)
from ollama_harness import Session
from troupe_runner_ollama.defaults import (
    DEFAULT_CONTEXT_LENGTH,
    PREFLIGHT_TIMEOUT_SECONDS,
    STOP_GRACE_SECONDS,
)
from troupe_runner_ollama.runner import Runner, _Exit

MARGIN = 5.0
"""Time allowed beyond the runner's own stop grace, for a loaded machine."""


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    path = tmp_path / "workspace"
    path.mkdir()
    return path


@pytest.fixture
def session(workspace: Path) -> Iterator[Session]:
    running = Session(workspace)
    try:
        yield running
    finally:
        running.kill()
        running.validate_all()


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port: int = sock.getsockname()[1]
        return port


def _options(fake: FakeOllama, **more: Any) -> dict[str, Any]:  # noqa: ANN401 - JSON values
    return {"model": "fake", "endpoint": fake.url, **more}


def _events(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [m["params"] for m in messages if m.get("method") == "run/event"]


def _error(response: dict[str, Any]) -> dict[str, Any]:
    data: dict[str, Any] = response["error"]["data"]
    return data


# Requirement: The runner identifies itself as ollama; the handshake


def test_initialize_names_the_runner_and_version_0(session: Session) -> None:
    answer = session.initialize()
    assert answer["result"]["protocolVersion"] == 0
    assert answer["result"]["runner"]["name"] == "ollama"


# Requirement: The Ollama runner uses transcript kinds


def _transcript(capabilities: list[str], workspace: Path) -> tuple[list[str], list[dict[str, Any]]]:
    """The capabilities the runner accepted, and its transcript records' params, for a run with one
    tool call, offered ``capabilities``."""
    session = Session(workspace, capabilities=capabilities)
    try:
        with serving([calls(tool_call("Glob", {"pattern": "*"})), final("done")]) as fake:
            session.start(_options(fake))
            messages = session.until_result()
        accepted = next(m for m in session.received if "capabilities" in m.get("result", {}))
        session.validate_all()
    finally:
        session.kill()
    records = [m["params"] for m in messages if m.get("method") == "run/transcript"]
    return accepted["result"]["capabilities"], records


def test_offered_transcript_kinds_it_accepts_and_every_record_has_a_kind(workspace: Path) -> None:
    accepted, records = _transcript(["transcript-kinds"], workspace)
    assert accepted == ["transcript-kinds"]
    assert {r["kind"] for r in records} == {"sent", "received"}
    assert records[0]["kind"] == "sent"


def test_offered_no_capability_it_sends_the_same_records_without_a_kind(
    workspace: Path, tmp_path: Path
) -> None:
    _, with_kinds = _transcript(["transcript-kinds"], workspace)
    other = tmp_path / "other"
    other.mkdir()
    accepted, without = _transcript([], other)
    assert accepted == []
    assert all("kind" not in r for r in without)
    scrubbed = [r["record"].replace(str(other), "<workspace>") for r in without]
    assert scrubbed == [r["record"].replace(str(workspace), "<workspace>") for r in with_kinds]


def test_an_unsupported_protocol_version_is_refused_naming_the_supported_ones(
    session: Session,
) -> None:
    data = _error(session.initialize([7]))
    assert data["code"] == "runner.unsupported-version"
    assert data["details"] == {"supportedVersions": [0]}


def test_a_whole_run_is_init_events_and_one_result_then_shutdown(session: Session) -> None:
    with serving([final("All done.")]) as fake:
        assert session.start(_options(fake))["result"] == {"runId": session.run_id}
        events = _events(session.until_result())
        assert session.request("shutdown", {})["result"] == {}
        assert session.wait() == 0
    assert events[0]["type"] == "init"
    assert events[0]["engine"] == {"name": "ollama", "version": "0.12.6", "model": "fake"}
    assert [event["seq"] for event in events] == list(range(len(events)))
    assert events[-1]["type"] == "result"
    assert events[-1]["status"] == "ok"


def test_a_second_run_start_is_refused(session: Session) -> None:
    with serving([final("hi")]) as fake:
        session.start(_options(fake))
        session.until_result()
        params = session.sent[-1]["params"]
        data = _error(session.request("run/start", params))
        assert data["code"] == "runner.already-started"


# Requirement: The runner's options are closed


def test_an_unknown_option_is_refused_and_no_run_starts(session: Session) -> None:
    with serving() as fake:
        response = session.start(_options(fake, troupeConformanceUnknownOption=1), valid=False)
        assert _error(response)["code"] == "ollama.unknown-option"
        assert _error(response)["details"] == {"where": "options.troupeConformanceUnknownOption"}
        assert fake.requests == []


def test_options_without_a_model_are_refused_naming_model(session: Session) -> None:
    response = session.start({}, valid=False)
    assert _error(response)["code"] == "ollama.invalid-options"
    assert _error(response)["details"] == {"where": "options.model"}


def test_credentials_in_the_endpoint_are_refused_without_repeating_them(session: Session) -> None:
    response = session.start(
        {"model": "fake", "endpoint": "http://user:secret@127.0.0.1:11434"}, valid=False
    )
    assert _error(response)["details"] == {"where": "options.endpoint"}
    assert all("secret" not in str(m) for m in session.received)


# Requirement: The runner checks the engine before it acknowledges the run


def test_nothing_listening_is_unreachable_naming_the_endpoint_and_the_fix(session: Session) -> None:
    endpoint = f"http://127.0.0.1:{_free_port()}"
    data = _error(session.start({"model": "fake", "endpoint": endpoint}))
    assert data["code"] == "ollama.unreachable"
    assert data["details"] == {"endpoint": endpoint}
    assert "ollama serve" in data["fix"]
    assert "options.endpoint" in data["fix"]


def test_a_silent_ollama_is_unreachable_within_the_preflight_limit(session: Session) -> None:
    with serving(settings=Settings(silent_preflight=True)) as fake:
        started = time.monotonic()
        data = _error(session.start(_options(fake)))
        assert data["code"] == "ollama.unreachable"
        assert time.monotonic() - started < 10 + MARGIN


def test_an_ollama_too_old_is_refused_naming_the_requirement(session: Session) -> None:
    with serving(settings=Settings(version="0.12.5")) as fake:
        data = _error(session.start(_options(fake)))
    assert data["code"] == "runner.requirement-unmet"
    assert data["details"] == {"requirement": "ollama", "wanted": ">= 0.12.6", "found": "0.12.5"}
    assert "Upgrade Ollama" in data["fix"]


def test_a_version_the_runner_cant_read_is_refused_naming_what_ollama_reported(
    session: Session,
) -> None:
    with serving(settings=Settings(version="latest")) as fake:
        data = _error(session.start(_options(fake)))
    assert data["code"] == "runner.requirement-unmet"
    assert data["details"]["found"] == "latest"


def test_a_model_that_isnt_pulled_is_refused_naming_ollama_pull(session: Session) -> None:
    with serving() as fake:
        data = _error(session.start(_options(fake, model="qwen3:4b")))
    assert data["code"] == "ollama.model-not-found"
    assert data["details"] == {"endpoint": fake.url, "model": "qwen3:4b"}
    assert data["fix"] == "Pull it with: ollama pull qwen3:4b"


def test_a_model_that_cant_call_tools_is_refused_naming_its_capabilities(session: Session) -> None:
    settings = Settings(models={"plain": {"capabilities": ["completion"]}})
    with serving(settings=settings) as fake:
        data = _error(session.start(_options(fake, model="plain")))
    assert data["code"] == "ollama.model-without-tools"
    assert data["details"] == {"model": "plain", "capabilities": ["completion"]}


def test_a_model_ollama_says_nothing_about_is_refused_saying_so(session: Session) -> None:
    settings = Settings(models={"old": {"details": {}}})
    with serving(settings=settings) as fake:
        data = _error(session.start(_options(fake, model="old")))
    assert data["code"] == "ollama.model-without-tools"
    assert data["details"] == {"model": "old"}
    assert "didn't say" in data["problem"]


# Requirement: The runner always sets the context window


def test_without_context_length_the_window_is_the_default(session: Session) -> None:
    with serving([final("hi")]) as fake:
        session.start(_options(fake))
        session.until_result()
    assert fake.chats()[0]["options"]["num_ctx"] == DEFAULT_CONTEXT_LENGTH


def test_a_model_with_a_smaller_maximum_gets_its_maximum(session: Session) -> None:
    small = {
        "capabilities": ["tools"],
        "model_info": {"general.architecture": "a", "a.context_length": 4096},
    }
    with serving([final("hi")], Settings(models={"small": small})) as fake:
        session.start(_options(fake, model="small"))
        session.until_result()
    assert fake.chats()[0]["options"]["num_ctx"] == 4096


def test_a_context_length_the_model_cant_hold_is_refused_naming_the_maximum(
    session: Session,
) -> None:
    with serving() as fake:
        data = _error(session.start(_options(fake, contextLength=50000)))
    assert data["code"] == "ollama.invalid-options"
    assert data["details"] == {"where": "options.contextLength"}
    assert "40960" in data["problem"]


# Stopping (design D3)


def test_cancel_while_an_answer_streams_closes_it_and_nothing_follows_the_answer(
    session: Session,
) -> None:
    with serving([Answer([message("a"), Line(b"{}", delay=60)])]) as fake:
        session.start(_options(fake))
        while not any(m.get("method") == "run/transcript" for m in session.received[2:]):
            session.message()
        cancel = session.send("run/cancel", {"runId": session.run_id})
        started = time.monotonic()
        after = session.rest()
        assert session.wait() == 0
        assert time.monotonic() - started < STOP_GRACE_SECONDS + MARGIN
        assert fake.closed_by_client.wait(5)
    answered = next(i for i, m in enumerate(after) if m.get("id") == cancel)
    assert after[answered + 1 :] == []


def test_end_of_input_while_a_request_waits_closes_it_and_the_runner_exits(
    session: Session,
) -> None:
    with serving([Answer([Line(b"{}", delay=60)])]) as fake:
        session.start(_options(fake))
        while not fake.chats():
            time.sleep(0.02)
        session.close_stdin()
        session.rest()
        assert session.wait() == 0
        assert fake.closed_by_client.wait(5)


def test_the_runner_takes_nothing_from_its_environment(workspace: Path) -> None:
    # OLLAMA_HOST would move the endpoint if the runner read it; it's never read (design D10).
    with serving([final("hi")]) as fake:
        running = Session(workspace, {"OLLAMA_HOST": f"127.0.0.1:{_free_port()}"})
        try:
            running.start({"model": "fake", "endpoint": fake.url})
            events = _events(running.until_result())
            assert events[-1]["status"] == "ok"
            assert len(fake.chats()) == 1
        finally:
            running.kill()
            running.validate_all()


def test_a_tool_call_runs_in_the_workspace_and_its_events_validate(
    session: Session, workspace: Path
) -> None:
    write = calls(tool_call("Write", {"file_path": "out/a.txt", "content": "hello"}))
    with serving([write, final("done")]) as fake:
        session.start(_options(fake), effects={"write": ["out/**"]})
        events = _events(session.until_result())
    assert (workspace / "out" / "a.txt").read_text(encoding="utf-8") == "hello"
    assert [e["type"] for e in events] == ["init", "tool_call", "tool_result", "turn", "result"]


class _Exploding:
    """A conversation that fails as a bug in the runner would."""

    def __init__(self) -> None:
        self.failed_with: str | None = None

    def run(self) -> None:
        raise KeyError("boom")

    def fail(self, message: str) -> None:
        self.failed_with = message


def test_a_failure_of_the_runner_itself_is_reported_and_its_exit_is_1() -> None:
    stdout, stderr = io.BytesIO(), io.BytesIO()
    runner = Runner(io.BytesIO(), stdout, stderr)
    conversation = _Exploding()
    runner._converse(conversation)  # type: ignore[arg-type]
    assert conversation.failed_with == "The Ollama runner failed: KeyError: 'boom'"
    assert b"the conversation failed" in stderr.getvalue()
    assert b"KeyError" in stderr.getvalue()
    with pytest.raises(_Exit) as exited:
        runner._end(1, None)
    assert exited.value.code == 1
    assert json.loads(stdout.getvalue().splitlines()[-1]) == {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {},
    }


# Found by a review of the code (troupe-run/troupe#283), each failing before its fix.


def test_a_scratch_directory_that_isnt_there_is_refused_never_acknowledged(
    workspace: Path,
) -> None:
    running = Session(workspace)
    try:
        with serving([final("hi")]) as fake:
            running.initialize()
            params = {
                "runId": running.run_id,
                "direction": "d",
                "workspace": str(workspace),
                "options": _options(fake),
                "limits": {"eventMaxBytes": 65536},
                "effects": {"write": [], "delete": [], "move": []},
                "scratch": str(workspace.parent / "no-such-scratch"),
            }
            data = _error(running.request("run/start", params))
            assert data["code"] == "runner.invalid-params"
            assert "scratch" in data["fix"]
            running.close_stdin()
            assert running.rest() == []
            assert running.wait() == 0
    finally:
        running.kill()
        running.validate_all()


@pytest.mark.parametrize("endpoint", ["http://[:]", "http://[1.2.3.4]:11434"])
def test_a_bracketed_endpoint_that_isnt_an_address_is_unreachable_not_a_crash(
    session: Session, endpoint: str
) -> None:
    data = _error(session.start({"model": "fake", "endpoint": endpoint}))
    assert data["code"] == "ollama.unreachable"
    assert "isn't an address" in data["problem"]


def test_both_preflight_requests_share_one_deadline(session: Session) -> None:
    # The version comes late, then the model never: with a limit for each request the refusal
    # would take nearly twice the limit; with one deadline for both it takes the limit.
    slow = Settings(version_delay=PREFLIGHT_TIMEOUT_SECONDS * 0.8, silent_show=True)
    with serving(settings=slow) as fake:
        started = time.monotonic()
        data = _error(session.start(_options(fake)))
        took = time.monotonic() - started
    assert data["code"] == "ollama.unreachable"
    assert took < PREFLIGHT_TIMEOUT_SECONDS + MARGIN


def test_a_protocol_version_of_false_isnt_version_0(session: Session) -> None:
    session.refused.add(1)  # the contract's schema refuses it too
    data = _error(session.initialize([False]))
    assert data["code"] == "runner.unsupported-version"


def test_a_lone_surrogate_from_ollama_leaves_no_gap_in_the_events(session: Session) -> None:
    # json.loads turns the \ud800 escape into a lone surrogate, which can't be UTF-8.
    answer = Answer(
        [b'{"message":{"role":"assistant","content":"x\\ud800y"},"done":false}', done()]
    )
    with serving([answer]) as fake:
        session.start(_options(fake))
        events = _events(session.until_result())
    assert [event["seq"] for event in events] == list(range(len(events)))
    assert events[-1]["status"] == "ok"


def test_end_of_input_after_the_runner_failed_exits_1() -> None:
    stdout, stderr = io.BytesIO(), io.BytesIO()
    runner = Runner(io.BytesIO(), stdout, stderr)
    runner._converse(_Exploding())  # type: ignore[arg-type]
    assert runner.run() == 1  # its standard input is already at its end
