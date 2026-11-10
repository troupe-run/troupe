"""The runner as troupe runs it: a process speaking the contract over standard input and output,
against the fake endpoint (spec: openai-runner; design D5). Every run uses TEST_LIMITS unless a
test says why not (design D7)."""

import base64
import json
import time
from collections.abc import Iterator
from importlib.metadata import version
from pathlib import Path
from typing import Any

import pytest

from fake_endpoint import (
    FakeEndpoint,
    Hold,
    Reply,
    error_reply,
    event,
    response,
    sse,
    text_reply,
    tool_reply,
)
from openai_harness import (
    CANARY,
    TEST_LIMITS,
    LimitsNotSetError,
    Session,
    check_limits,
)

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
    capabilities: list[str] | None = None,
) -> Session:
    session = Session(workspace, credential, env, capabilities)
    sessions.append(session)
    return session


def _events(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [m["params"] for m in messages if m.get("method") == "run/event"]


def _handshake(session: Session) -> dict[str, Any]:
    """The runner's answer to initialize."""
    return next(m for m in session.received if "capabilities" in m.get("result", {}))


def _records(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Each run/transcript notification's params: its record, kind and encoding."""
    return [m["params"] for m in messages if m.get("method") == "run/transcript"]


# The handshake and init


def test_the_runner_names_itself_openai(sessions: list[Session], workspace: Path) -> None:
    answer = _session(sessions, workspace).initialize()
    assert answer["result"]["runner"] == {
        "name": "openai",
        "version": version("troupe-runner-openai"),
    }


def test_init_comes_first_naming_the_engine_the_model_the_tools_and_checked(
    sessions: list[Session], workspace: Path
) -> None:
    with FakeEndpoint([text_reply("Done.")]) as fake:
        session = _session(sessions, workspace)
        assert "result" in session.start(fake.endpoint, model="fake-model")
        events = _events(session.until_result())
    init = events[0]
    assert (init["seq"], init["type"], init["effects"]) == (0, "init", "checked")
    assert init["engine"] == {"name": "responses", "model": "fake-model"}
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
        ({"endpoint": "https://elsewhere.example/v1", **TEST_LIMITS}, "openai.unknown-option"),
        ({"maxTurns": 0}, "openai.invalid-options"),
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
    assert answer["error"]["data"]["code"] == "openai.no-runtime"


def test_plain_http_to_another_host_with_a_credential_is_refused(
    sessions: list[Session], workspace: Path
) -> None:
    answer = _session(sessions, workspace).start("http://models.example.com/v1")
    assert answer["error"]["data"]["code"] == "openai.insecure-endpoint"
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
    assert answer["error"]["data"]["code"] == "openai.credential-mismatch"
    assert CANARY not in json.dumps(answer)


def test_a_key_read_with_its_line_ending_is_refused_without_any_part_of_it(
    sessions: list[Session], workspace: Path
) -> None:
    with FakeEndpoint() as fake:
        session = _session(sessions, workspace, credential=CANARY + "\r\n")
        answer = session.start(fake.endpoint)
        assert fake.requests == []
    assert answer["error"]["data"]["code"] == "openai.malformed-credential"
    assert CANARY[:8] not in json.dumps(answer)


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


def test_the_transcript_is_the_exchange_with_kinds_and_no_request_header(
    sessions: list[Session], workspace: Path
) -> None:
    with FakeEndpoint([text_reply("Done.")]) as fake:
        session = _session(sessions, workspace)
        session.start(fake.endpoint)
        records = _records(session.until_result())
        answer = _handshake(session)
        assert json.loads(records[0]["record"]) == fake.requests[0].json()
    assert answer["result"]["capabilities"] == ["transcript-kinds"]
    assert [r["kind"] for r in records[:2]] == ["sent", "note"]
    assert {r["kind"] for r in records[2:]} == {"received"}
    assert all("authorization" not in json.dumps(r).lower() for r in records)


def test_offered_no_capability_it_sends_the_same_records_without_a_kind(
    sessions: list[Session], workspace: Path
) -> None:
    runs = []
    for capabilities in (["transcript-kinds"], []):
        with FakeEndpoint([text_reply("Done.")]) as fake:
            session = _session(sessions, workspace, capabilities=capabilities)
            session.start(fake.endpoint)
            runs.append((_handshake(session), _records(session.until_result())))
    (_, with_kinds), (answer, without) = runs
    assert answer["result"]["capabilities"] == []
    assert all("kind" not in r for r in without)
    assert [r["record"] for r in without] == [r["record"] for r in with_kinds]


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
    body = next(r for r in _records(messages) if r["record"].startswith('{"error"'))
    assert body["kind"] == "received"
    assert "[credential]" in body["record"]
    assert MASKED_ECHO not in json.dumps(messages)


def test_a_body_that_isnt_utf_8_is_sent_as_base64_with_the_credential_masked_first(
    sessions: list[Session], workspace: Path
) -> None:
    body = b"\xff refused " + CANARY.encode() + b" \xfe"
    with FakeEndpoint([Reply(400, body=body)]) as fake:
        session = _session(sessions, workspace)
        session.start(fake.endpoint)
        records = _records(session.until_result())
    [binary] = [r for r in records if r.get("encoding") == "base64"]
    assert binary["kind"] == "received"
    assert base64.b64decode(binary["record"]) == b"\xff refused [credential] \xfe"


SCRIPTS: dict[str, list[Reply]] = {
    "success": [tool_reply([("c1", "Glob", {"pattern": "*"})]), text_reply(f"done {CANARY}")],
    "rejected": [error_reply(401, f"Incorrect API key provided: {MASKED_ECHO}.")],
    # Retry-After: 0 keeps every retry until they run out, without the real backoff between them.
    "server errors": [error_reply(500, f"boom {CANARY}", headers=[("Retry-After", "0")])] * 5,
    "quota": [error_reply(429, f"quota for {CANARY}", code="insufficient_quota")],
    "redirect": [Reply(307, headers=[("Location", f"https://x.example/{CANARY}")])],
    "tool echo": [
        tool_reply([("c1", "Read", {"file_path": f"{CANARY}.txt"})]),
        text_reply("ok"),
    ],
    # A finished event that isn't JSON: the result quotes its start, so the canary is in it.
    "wrong shape": [Reply(lines=[f"data: not json {CANARY}", ""])],
    # A 200 that isn't a stream: the result quotes its body, and the transcript records it.
    "not a stream": [
        Reply(200, body=json.dumps({"error": {"message": f"for {MASKED_ECHO}"}}).encode())
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

HELD = Reply(
    lines=sse([event("response.created", response=response([], status="in_progress")), Hold()])
)
"""A response the service has started, then holds open: a well-formed first event, then nothing,
so the runner is still reading it when it's stopped."""

STOPPED_WITHIN = 3.0
"""Seconds from a stop to the held request's connection closing."""

REQUEST_WITHIN = 30.0
"""Seconds from the runner's init to its first request reaching the fake, on a slow machine. The
stop tests wait for the request rather than sleeping, so they stop a request that's really in
flight however long it took to send (#359)."""


def test_cancel_during_a_held_response_closes_it_and_exits_without_a_result(
    sessions: list[Session], workspace: Path
) -> None:
    with FakeEndpoint([HELD]) as fake:
        session = _session(sessions, workspace)
        session.start(fake.endpoint)
        assert session.message()["params"]["type"] == "init"
        assert fake.wait_for_requests(1, REQUEST_WITHIN), "the runner never sent its request"
        assert len(fake.requests) == 1
        assert not fake.wait_for_client_to_close(0), "the request ended before the cancel"
        started = time.monotonic()
        answer = session.request("run/cancel", {"runId": session.run_id})
        # Closed by the cancel, not by the runner's exit: a runner that only exits takes longer.
        assert fake.wait_for_client_to_close(STOPPED_WITHIN)
        rest = session.rest()
        code = session.wait()
    assert answer["result"] == {}
    assert time.monotonic() - started < 10
    assert all(e["type"] != "result" for e in _events(rest))
    assert code == 0
    session.validate_all()


def test_end_of_input_mid_run_stops_the_request_and_exits(
    sessions: list[Session], workspace: Path
) -> None:
    with FakeEndpoint([HELD]) as fake:
        session = _session(sessions, workspace)
        session.start(fake.endpoint)
        session.message()
        assert fake.wait_for_requests(1, REQUEST_WITHIN), "the runner never sent its request"
        assert len(fake.requests) == 1
        assert not fake.wait_for_client_to_close(0), "the request ended before end of input"
        session.close_stdin()
        assert fake.wait_for_client_to_close(STOPPED_WITHIN)
        assert session.wait() == 0


# The test limits


def test_a_run_started_on_the_real_use_limits_is_refused_by_the_harness() -> None:
    with pytest.raises(LimitsNotSetError):
        check_limits({}, None)
    check_limits(TEST_LIMITS, None)
    check_limits({"maxTurns": 3}, None)
    check_limits({}, "refused before any request")
