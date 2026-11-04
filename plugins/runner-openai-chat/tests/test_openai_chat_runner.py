"""The runner as troupe runs it: a process speaking the contract over standard input and output,
against the fake endpoint (spec: openai-chat-runner; design D5). Every run uses TEST_LIMITS unless a
test says why not (design D7)."""

import json
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from chat_harness import (
    CANARY,
    TEST_LIMITS,
    LimitsNotSetError,
    Session,
    check_limits,
)
from fake_endpoint import FakeEndpoint, Hold, Reply, error_reply, text_reply, tool_reply

MASKED_ECHO = "sk-cana*********6789"


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    path = tmp_path / "workspace"
    path.mkdir()
    return path


@pytest.fixture
def sessions() -> Iterator[list[Session]]:
    started: list[Session] = []
    yield started
    for session in started:
        session.kill()


def _session(
    sessions: list[Session],
    workspace: Path,
    credential: str | None = CANARY,
    env: dict[str, str] | None = None,
) -> Session:
    session = Session(workspace, credential, env)
    sessions.append(session)
    return session


def _events(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [m["params"] for m in messages if m.get("method") == "run/event"]


def _records(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        json.loads(m["params"]["record"]) for m in messages if m.get("method") == "run/transcript"
    ]


# The handshake and init


def test_the_runner_names_itself_openai_chat(sessions: list[Session], workspace: Path) -> None:
    answer = _session(sessions, workspace).initialize()
    assert answer["result"]["runner"] == {"name": "openai-chat", "version": "0.0.0"}


def test_init_comes_first_naming_the_engine_the_model_the_tools_and_checked(
    sessions: list[Session], workspace: Path
) -> None:
    with FakeEndpoint([text_reply("Done.")]) as fake:
        session = _session(sessions, workspace)
        assert "result" in session.start(fake.endpoint, model="fake-model")
        events = _events(session.until_result())
    init = events[0]
    assert (init["seq"], init["type"], init["effects"]) == (0, "init", "checked")
    assert init["engine"] == {"name": "chat-completions", "model": "fake-model"}
    assert init["tools"] == ["Read", "Write", "Edit", "Glob", "Grep", "Delete", "Move"]
    assert [e["seq"] for e in events] == list(range(len(events)))


def test_a_whole_run_ends_ok_shuts_down_cleanly_and_every_message_is_valid(
    sessions: list[Session], workspace: Path
) -> None:
    with FakeEndpoint(
        [tool_reply([("c1", "Glob", {"pattern": "*"})]), text_reply("Done.")]
    ) as fake:
        session = _session(sessions, workspace)
        session.start(fake.endpoint)
        result = _events(session.until_result())[-1]
        assert session.shutdown() == 0
    assert (result["status"], result["message"]) == ("ok", "Done.")
    session.validate_all()


# What run/start refuses, before any request


@pytest.mark.parametrize(
    ("options", "code"),
    [
        ({"endpoint": "https://elsewhere.example/v1", **TEST_LIMITS}, "openai-chat.unknown-option"),
        ({"maxTurns": 0}, "openai-chat.invalid-options"),
    ],
)
def test_bad_options_are_refused_before_any_request(
    sessions: list[Session], workspace: Path, options: dict[str, Any], code: str
) -> None:
    with FakeEndpoint() as fake:
        session = _session(sessions, workspace)
        answer = session.start(fake.endpoint, options, own_limits="refused before any request")
        assert fake.requests == []
    assert answer["error"]["data"]["code"] == code


def test_a_run_start_without_a_runtime_is_refused(sessions: list[Session], workspace: Path) -> None:
    answer = _session(sessions, workspace, credential=None).start(None)
    assert answer["error"]["data"]["code"] == "openai-chat.no-runtime"


def test_plain_http_to_another_host_with_a_credential_is_refused(
    sessions: list[Session], workspace: Path
) -> None:
    answer = _session(sessions, workspace).start("http://models.example.com/v1")
    assert answer["error"]["data"]["code"] == "openai-chat.insecure-endpoint"
    assert answer["error"]["data"]["details"] == {"endpoint": "http://models.example.com/v1"}


def test_a_credential_the_runtime_doesnt_mention_is_refused_without_its_value(
    sessions: list[Session], workspace: Path
) -> None:
    with FakeEndpoint() as fake:
        session = _session(
            sessions, workspace, credential=None, env={"TROUPE_RUNTIME_CREDENTIAL": CANARY}
        )
        answer = session.start(fake.endpoint)
        assert fake.requests == []
    assert answer["error"]["data"]["code"] == "openai-chat.credential-mismatch"
    assert CANARY not in json.dumps(answer)


def test_a_second_run_start_is_refused_and_the_first_run_goes_on(
    sessions: list[Session], workspace: Path
) -> None:
    with FakeEndpoint([text_reply("Done.")]) as fake:
        session = _session(sessions, workspace)
        session.start(fake.endpoint)
        second = session.request("run/start", session.sent[-1]["params"])
        result = _events(session.until_result())[-1]
    assert second["error"]["data"]["code"] == "runner.already-started"
    assert result["status"] == "ok"


# The credential and the transcript


def test_the_transcript_is_the_exchange_framed_with_no_request_header(
    sessions: list[Session], workspace: Path
) -> None:
    with FakeEndpoint([text_reply("Done.")]) as fake:
        session = _session(sessions, workspace)
        session.start(fake.endpoint)
        records = _records(session.until_result())
    assert [r["kind"] for r in records[:2]] == ["request", "response"]
    assert json.loads(records[0]["body"])["model"] == "fake-model"
    assert {r["kind"] for r in records[2:]} == {"stream"}
    assert all("authorization" not in json.dumps(r).lower() for r in records)


def test_a_401_that_echoes_part_of_the_key_is_masked_in_the_result_and_transcript(
    sessions: list[Session], workspace: Path
) -> None:
    reply = error_reply(401, f"Incorrect API key provided: {MASKED_ECHO}.", code="invalid_api_key")
    with FakeEndpoint([reply]) as fake:
        session = _session(sessions, workspace)
        session.start(fake.endpoint)
        messages = session.until_result()
        assert fake.requests[0].headers["authorization"] == f"Bearer {CANARY}"
    result = _events(messages)[-1]
    assert result["status"] == "error"
    assert "Incorrect API key provided: [credential]." in result["message"]
    body = next(r for r in _records(messages) if r["kind"] == "body")
    assert "[credential]" in body["body"]
    assert MASKED_ECHO not in json.dumps(messages)


SCRIPTS: dict[str, list[Reply]] = {
    "success": [tool_reply([("c1", "Glob", {"pattern": "*"})]), text_reply(f"done {CANARY}")],
    "rejected": [error_reply(401, f"Incorrect API key provided: {MASKED_ECHO}.")],
    "server errors": [error_reply(500, f"boom {CANARY}")] * 5,
    "quota": [error_reply(429, f"quota for {CANARY}", code="insufficient_quota")],
    "redirect": [Reply(307, headers=[("Location", f"https://x.example/{CANARY}")])],
    "tool echo": [
        tool_reply([("c1", "Read", {"file_path": f"{CANARY}.txt"})]),
        text_reply("ok"),
    ],
}


@pytest.mark.parametrize("name", SCRIPTS)
def test_the_credential_is_nowhere_in_what_the_runner_writes_however_the_run_ends(
    sessions: list[Session], workspace: Path, name: str
) -> None:
    with FakeEndpoint(SCRIPTS[name]) as fake:
        session = _session(sessions, workspace)
        session.start(fake.endpoint)
        session.until_result()
        session.shutdown()
        assert all(r.headers.get("authorization") == f"Bearer {CANARY}" for r in fake.requests)
    written = b"".join(session.raw) + session.stderr()
    for secret in (CANARY, MASKED_ECHO, CANARY[:-1]):
        assert secret.encode() not in written


# Stopping


def test_cancel_during_a_held_response_closes_it_and_exits_without_a_result(
    sessions: list[Session], workspace: Path
) -> None:
    with FakeEndpoint([Reply(lines=["data: {}", "", Hold()])]) as fake:
        session = _session(sessions, workspace)
        session.start(fake.endpoint)
        assert session.message()["params"]["type"] == "init"
        time.sleep(0.3)
        started = time.monotonic()
        answer = session.request("run/cancel", {"runId": session.run_id})
        rest = session.rest()
        code = session.wait()
        assert fake.wait_for_client_to_close(5)
    assert answer["result"] == {}
    assert time.monotonic() - started < 10
    assert all(e["type"] != "result" for e in _events(rest))
    assert code == 0
    session.validate_all()


def test_end_of_input_mid_run_stops_the_request_and_exits(
    sessions: list[Session], workspace: Path
) -> None:
    with FakeEndpoint([Reply(lines=["data: {}", "", Hold()])]) as fake:
        session = _session(sessions, workspace)
        session.start(fake.endpoint)
        session.message()
        time.sleep(0.3)
        session.close_stdin()
        assert session.wait() == 0
        assert fake.wait_for_client_to_close(5)


# The test limits


def test_a_run_started_on_the_real_use_limits_is_refused_by_the_harness() -> None:
    with pytest.raises(LimitsNotSetError):
        check_limits({}, None)
    check_limits(TEST_LIMITS, None)
    check_limits({"maxTurns": 3}, None)
    check_limits({}, "refused before any request")
