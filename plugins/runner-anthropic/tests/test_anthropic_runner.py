"""The runner as troupe runs it: a process speaking the contract over standard input and output,
against the fake Messages API (spec: anthropic-runner; design D4, D6, D9, D11). Every run uses
TEST_LIMITS unless a test says why not."""

import json
import threading
import time
from collections.abc import Iterator
from importlib.metadata import version
from pathlib import Path
from typing import Any

import pytest

from anthropic_harness import CANARY, TEST_LIMITS, Session
from fake_messages import (
    FakeEndpoint,
    Gate,
    Hold,
    Reply,
    error_reply,
    sse,
    start,
    stream_error_reply,
    text_reply,
    tool_reply,
)
from troupe_plugin_sdk.tools import Tools

MASKED_ECHO = "sk-ant-ca*********6789"
"""How a 401 may quote the canary with part of it hidden."""

GRACE = 10.0
"""troupe's cancel grace: the runner must have exited this long after a stop."""

STOPPED_WITHIN = 3.0
"""Seconds from a stop to the held request's connection closing."""

REQUEST_WITHIN = 30.0
"""Seconds from run/start to its first request reaching the fake, on a slow machine. The stop
tests wait for the request rather than sleeping, so they stop a request that's really in flight."""


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


def _records(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Each run/transcript notification's params: its record, kind and encoding."""
    return [m["params"] for m in messages if m.get("method") == "run/transcript"]


def _handshake(session: Session) -> dict[str, Any]:
    """The runner's answer to initialize."""
    return next(m for m in session.received if "capabilities" in m.get("result", {}))


# Requirement: The Anthropic runner is a self-contained plugin


def test_the_runner_names_itself_anthropic_with_its_packages_version(
    sessions: list[Session], workspace: Path
) -> None:
    session = _session(sessions, workspace)
    answer = session.initialize()
    assert answer["result"]["runner"] == {
        "name": "anthropic",
        "version": version("troupe-runner-anthropic"),
    }
    session.close_stdin()
    session.wait()
    session.validate_all()


def test_init_comes_first_naming_the_messages_engine_the_model_the_tools_and_checked(
    sessions: list[Session], workspace: Path
) -> None:
    with FakeEndpoint([text_reply("Done.")]) as fake:
        session = _session(sessions, workspace)
        assert "result" in session.start(fake.endpoint, model="small-model")
        events = _events(session.until_result())
        assert [r.json()["model"] for r in fake.requests] == ["small-model"]
    init = events[0]
    assert (init["seq"], init["type"], init["effects"]) == (0, "init", "checked")
    assert init["runner"]["name"] == "anthropic"
    assert init["engine"] == {"name": "messages", "model": "small-model"}
    assert init["tools"] == Tools.names()
    assert [e["seq"] for e in events] == list(range(len(events)))
    session.validate_all()


def test_a_whole_run_ends_ok_shuts_down_cleanly_and_every_message_is_valid(
    sessions: list[Session], workspace: Path
) -> None:
    with FakeEndpoint(
        [tool_reply([("t1", "Glob", {"pattern": "*"})]), text_reply("Done.")]
    ) as fake:
        session = _session(sessions, workspace)
        session.start(fake.endpoint)
        result = _events(session.until_result())[-1]
        assert session.shutdown() == 0
        assert [(r.method, r.path) for r in fake.requests] == [("POST", "/v1/messages")] * 2
    assert (result["status"], result["message"]) == ("ok", "Done.")
    session.validate_all()


# What run/start refuses, before any request (design D6)


@pytest.mark.parametrize(
    ("options", "code", "where"),
    [
        (
            {"endpoint": "https://elsewhere.example", **TEST_LIMITS},
            "anthropic.unknown-option",
            "options.endpoint",
        ),
        (
            {"troupeConformanceUnknownOption": 1, **TEST_LIMITS},
            "anthropic.unknown-option",
            "options.troupeConformanceUnknownOption",
        ),
        (
            {"maxOutputTokens": 0, **TEST_LIMITS},
            "anthropic.invalid-options",
            "options.maxOutputTokens",
        ),
        (
            {"contextWindow": "big", **TEST_LIMITS},
            "anthropic.invalid-options",
            "options.contextWindow",
        ),
    ],
)
def test_bad_options_are_refused_naming_the_option_before_any_request(
    sessions: list[Session], workspace: Path, options: dict[str, Any], code: str, where: str
) -> None:
    with FakeEndpoint() as fake:
        session = _session(sessions, workspace)
        answer = session.start(fake.endpoint, options, valid=False)
        session.close_stdin()
        session.wait()
        assert fake.requests == []
    data = answer["error"]["data"]
    assert (data["code"], data["details"]["where"]) == (code, where)
    session.validate_all()


def test_a_run_start_without_a_runtime_is_refused_saying_to_name_one(
    sessions: list[Session], workspace: Path
) -> None:
    session = _session(sessions, workspace, credential=None)
    answer = session.start(None)
    data = answer["error"]["data"]
    assert data["code"] == "anthropic.no-runtime"
    assert "runtime" in data["fix"]
    session.validate_all()


def test_an_openai_style_base_is_refused_naming_the_endpoint_to_use_before_any_request(
    sessions: list[Session], workspace: Path
) -> None:
    with FakeEndpoint() as fake:
        session = _session(sessions, workspace)
        answer = session.start(fake.endpoint + "/v1")
        session.close_stdin()
        session.wait()
        assert fake.requests == []
    data = answer["error"]["data"]
    assert (data["code"], data["details"]["where"]) == (
        "anthropic.unsupported-endpoint",
        "runtime.endpoint",
    )
    assert f"{fake.endpoint}." in data["fix"]
    assert "/v1/messages" in data["problem"]


def test_plain_http_to_another_host_with_a_credential_is_refused(
    sessions: list[Session], workspace: Path
) -> None:
    answer = _session(sessions, workspace).start("http://models.example.com")
    data = answer["error"]["data"]
    assert data["code"] == "anthropic.insecure-endpoint"
    assert data["details"] == {"endpoint": "http://models.example.com"}


@pytest.mark.parametrize(
    ("credential", "env"),
    [
        (None, {"TROUPE_RUNTIME_CREDENTIAL": CANARY}),  # run/start says none; the variable is set
        ("", {}),  # run/start says one; the variable is empty
    ],
    ids=["unmentioned", "missing"],
)
def test_a_credential_run_start_and_the_environment_disagree_on_is_refused_without_its_value(
    sessions: list[Session],
    workspace: Path,
    credential: str | None,
    env: dict[str, str],
) -> None:
    with FakeEndpoint() as fake:
        session = _session(sessions, workspace, credential=credential, env=env)
        answer = session.start(fake.endpoint)
        session.close_stdin()
        session.wait()
        assert fake.requests == []
    assert answer["error"]["data"]["code"] == "anthropic.credential-mismatch"
    assert CANARY[:8] not in json.dumps(answer)


@pytest.mark.parametrize("credential", [CANARY + "\r\n", "sk-ant-€" + CANARY])
def test_a_malformed_key_is_refused_without_any_part_of_it_before_any_request(
    sessions: list[Session], workspace: Path, credential: str
) -> None:
    with FakeEndpoint() as fake:
        session = _session(sessions, workspace, credential=credential)
        answer = session.start(fake.endpoint)
        session.close_stdin()
        session.wait()
        assert fake.requests == []
    data = answer["error"]["data"]
    assert (data["code"], data["details"]["where"]) == (
        "anthropic.malformed-credential",
        "TROUPE_RUNTIME_CREDENTIAL",
    )
    assert CANARY[:8] not in json.dumps(answer)


# Requirement: The credential goes only in the Authorization header; A service's echo of the
# credential is masked

SCRIPTS: dict[str, list[Reply]] = {
    "success": [tool_reply([("t1", "Glob", {"pattern": "*"})]), text_reply(f"done {CANARY}")],
    "rejected": [error_reply(401, f"invalid x-api-key: {MASKED_ECHO}", "authentication_error")],
    # Retry-After: 0 keeps every retry until they run out, without the real backoff between them.
    "server errors": [error_reply(500, f"boom {CANARY}", "api_error", [("Retry-After", "0")])] * 5,
    "billing": [error_reply(402, f"no credit for {CANARY}", "billing_error")],
    "redirect": [Reply(307, headers=[("Location", f"https://x.example/{CANARY}")], body=b"")],
    "tool echo": [
        tool_reply([("t1", "Read", {"file_path": f"{CANARY}.txt"})], text=f"reading {CANARY}"),
        text_reply("ok"),
    ],
    "stream error": [
        Reply(
            lines=sse(
                [
                    start(),
                    {
                        "type": "error",
                        "error": {"type": "invalid_request_error", "message": CANARY},
                    },
                ]
            )
        )
    ],
    # An event that isn't JSON: the result quotes the parser's words, the transcript the event.
    "not json": [Reply(lines=[*sse([start()]), f"data: not json {CANARY}", ""])],
    # A 200 that isn't a stream: the transcript records its body.
    "not a stream": [Reply(200, body=json.dumps({"error": f"for {MASKED_ECHO}"}).encode())],
}


@pytest.mark.parametrize("name", SCRIPTS)
def test_the_credential_is_only_in_authorization_and_nowhere_the_runner_writes_however_it_ends(
    sessions: list[Session], workspace: Path, name: str
) -> None:
    with FakeEndpoint(SCRIPTS[name]) as fake:
        session = _session(sessions, workspace, env={"ANTHROPIC_LOG": "debug"})
        session.start(fake.endpoint)
        session.until_result()
        assert session.shutdown() == 0
        requests = fake.requests
    assert requests
    for request in requests:
        assert request.headers["authorization"] == f"Bearer {CANARY}"
        others = {k: v for k, v in request.headers.items() if k != "authorization"}
        assert CANARY not in json.dumps(others)
    written = b"".join(session.raw) + session.stderr()
    for secret in (CANARY, MASKED_ECHO, CANARY[:-1]):
        assert secret.encode() not in written
    session.validate_all()


def test_without_a_credential_requests_carry_neither_authorization_nor_x_api_key(
    sessions: list[Session], workspace: Path
) -> None:
    with FakeEndpoint([text_reply("Done.")]) as fake:
        session = _session(sessions, workspace, credential=None)
        session.start(fake.endpoint)
        session.until_result()
        (request,) = fake.requests
    assert "authorization" not in request.headers
    assert "x-api-key" not in request.headers


def test_a_401_that_quotes_part_of_the_key_is_masked_in_the_result_and_the_transcript(
    sessions: list[Session], workspace: Path
) -> None:
    reply = error_reply(401, f"invalid x-api-key: {MASKED_ECHO}", "authentication_error")
    with FakeEndpoint([reply]) as fake:
        session = _session(sessions, workspace)
        session.start(fake.endpoint)
        messages = session.until_result()
        assert len(fake.requests) == 1
    result = _events(messages)[-1]
    assert (result["status"], result["reason"]) == ("error", "authentication")
    assert "invalid x-api-key: [credential]" in result["message"]
    body = next(r for r in _records(messages) if '"authentication_error"' in r["record"])
    assert body["kind"] == "received"
    assert "[credential]" in body["record"]
    assert MASKED_ECHO not in json.dumps(messages)


def test_an_error_body_that_isnt_utf_8_is_recorded_as_the_library_decoded_it_and_masked(
    sessions: list[Session], workspace: Path
) -> None:
    # The library hands the runner an error body as text it decoded, each byte that isn't UTF-8
    # replaced (design D11: error bodies as the library gives them), so nothing needs base64.
    body = b"\xff refused " + CANARY.encode() + b" \xfe"
    with FakeEndpoint([Reply(400, body=body)]) as fake:
        session = _session(sessions, workspace)
        session.start(fake.endpoint)
        messages = session.until_result()
        assert len(fake.requests) == 1
    records = _records(messages)
    assert all("encoding" not in r for r in records)
    (received,) = [r for r in records if r["kind"] == "received"]
    assert received["record"] == "� refused [credential] �"
    assert CANARY not in json.dumps(messages)


# Requirement: The library finds nothing of its own; The library's own logging stays out of the
# run's output

ENV_KEY = "sk-ant-env-key-canary-987"
ENV_TOKEN = "env-auth-token-canary-987"  # noqa: S105 - a canary, not a secret


def test_the_librarys_variables_in_the_runners_environment_change_nothing(
    sessions: list[Session], workspace: Path
) -> None:
    with FakeEndpoint([text_reply("elsewhere")]) as elsewhere:
        env = {
            "ANTHROPIC_API_KEY": ENV_KEY,
            "ANTHROPIC_AUTH_TOKEN": ENV_TOKEN,
            "ANTHROPIC_BASE_URL": elsewhere.endpoint,
            "ANTHROPIC_CUSTOM_HEADERS": "X-Leak: from-the-environment",
            "ANTHROPIC_LOG": "debug",
        }
        script = [tool_reply([("t1", "Glob", {"pattern": "*"})]), text_reply("Done.")]
        with FakeEndpoint(script) as fake:
            session = _session(sessions, workspace, credential=None, env=env)
            session.start(fake.endpoint)
            result = _events(session.until_result())[-1]
            assert session.shutdown() == 0
            requests = fake.requests
        assert elsewhere.requests == []
    assert result["status"] == "ok"
    assert len(requests) == 2
    for request in requests:
        assert "authorization" not in request.headers
        assert "x-api-key" not in request.headers
        assert "x-leak" not in request.headers
    for line in session.raw:
        assert json.loads(line)["jsonrpc"] == "2.0"
    stderr = session.stderr()
    for leaked in (b"authorization", b"Authorization", b"x-api-key", b"X-Leak", ENV_KEY.encode()):
        assert leaked not in stderr
    session.validate_all()


def test_an_active_profile_under_anthropic_config_dir_sends_no_token(
    sessions: list[Session], workspace: Path, tmp_path: Path
) -> None:
    config = tmp_path / "anthropic"
    (config / "configs").mkdir(parents=True)
    (config / "credentials").mkdir()
    (config / "active_config").write_text("work", encoding="utf-8")
    (config / "configs" / "work.json").write_text(
        json.dumps({"authentication": {"type": "user_oauth"}}), encoding="utf-8"
    )
    secret = config / "credentials" / "work.json"
    secret.write_text(json.dumps({"access_token": ENV_TOKEN, "expires_at": None}), "utf-8")
    secret.chmod(0o600)
    with FakeEndpoint([text_reply("Done.")]) as fake:
        session = _session(
            sessions, workspace, credential=None, env={"ANTHROPIC_CONFIG_DIR": str(config)}
        )
        session.start(fake.endpoint)
        session.until_result()
        (request,) = fake.requests
    assert "authorization" not in request.headers
    assert ENV_TOKEN not in json.dumps(request.headers)


# Requirement: The transcript is what the library exposes


def test_the_transcript_is_the_params_sent_a_status_note_then_each_event_with_no_request_header(
    sessions: list[Session], workspace: Path
) -> None:
    with FakeEndpoint([text_reply("Done.")]) as fake:
        session = _session(sessions, workspace)
        session.start(fake.endpoint)
        records = _records(session.until_result())
        sent = fake.requests[0].json()
    assert _handshake(session)["result"]["capabilities"] == ["transcript-kinds"]
    assert [r["kind"] for r in records[:2]] == ["sent", "note"]
    assert {r["kind"] for r in records[2:]} == {"received"}
    assert json.loads(records[0]["record"]) == {k: v for k, v in sent.items() if k != "stream"}
    assert json.loads(records[1]["record"])["status"] == 200
    assert [json.loads(r["record"])["type"] for r in records[2:]][-1] == "message_stop"
    for record in records:
        lowered = record["record"].lower()
        assert "authorization" not in lowered
        assert "x-api-key" not in lowered
        assert "user-agent" not in lowered


def test_offered_no_capability_it_answers_none_and_sends_the_same_records_without_a_kind(
    sessions: list[Session], workspace: Path
) -> None:
    runs = []
    for capabilities in (["transcript-kinds"], []):
        with FakeEndpoint([text_reply("Done.")]) as fake:
            session = _session(sessions, workspace, capabilities=capabilities)
            session.start(fake.endpoint)
            runs.append((_handshake(session), _records(session.until_result())))
            session.shutdown()
            session.validate_all()
    (_, with_kinds), (answer, without) = runs
    assert answer["result"]["capabilities"] == []
    assert all("kind" not in r for r in without)
    assert [r["record"] for r in without] == [r["record"] for r in with_kinds]


# Requirement: Cancel and end of input stop the request in flight

HELD = Reply(lines=sse([start(), Hold()]))
"""A reply the service has started, then holds open: a well-formed first event, then nothing, so
the runner is still reading it when it's stopped."""


def _held(sessions: list[Session], workspace: Path, fake: FakeEndpoint) -> Session:
    """A session whose one request is in flight, held open by the fake."""
    session = _session(sessions, workspace)
    session.start(fake.endpoint)
    assert session.message()["params"]["type"] == "init"
    assert fake.wait_for_requests(1, REQUEST_WITHIN), "the runner never sent its request"
    assert not fake.wait_for_client_to_close(0), "the request ended before the stop"
    return session


def test_cancel_during_a_held_reply_closes_it_and_exits_within_the_grace_without_a_result(
    sessions: list[Session], workspace: Path
) -> None:
    with FakeEndpoint([HELD]) as fake:
        session = _held(sessions, workspace, fake)
        started = time.monotonic()
        answer = session.request("run/cancel", {"runId": session.run_id})
        assert fake.wait_for_client_to_close(STOPPED_WITHIN)
        rest = session.rest()
        code = session.wait(GRACE)
        assert len(fake.requests) == 1
    assert answer["result"] == {}
    assert time.monotonic() - started < GRACE
    assert all(e["type"] != "result" for e in _events([*session.received, *rest]))
    assert code == 0
    session.validate_all()


def test_end_of_input_during_a_held_reply_closes_it_and_exits_within_the_grace(
    sessions: list[Session], workspace: Path
) -> None:
    with FakeEndpoint([HELD]) as fake:
        session = _held(sessions, workspace, fake)
        started = time.monotonic()
        session.close_stdin()
        assert fake.wait_for_client_to_close(STOPPED_WITHIN)
        rest = session.rest()
        code = session.wait(GRACE)
        assert len(fake.requests) == 1
    assert time.monotonic() - started < GRACE
    assert all(e["type"] != "result" for e in _events(rest))
    assert code == 0
    session.validate_all()


SLOW_FILES = {f"slow{n}.txt": ("x" * 14 + "\n") * 100 for n in range(20)}
"""Files a Grep for SLOW_PATTERN takes a second or more to search, reading and matching one line
at a time, so the runner's other thread can take a cancel while it runs."""

SLOW_PATTERN = "(x+x+)+y"


def test_a_cancel_while_a_replys_calls_are_carried_out_carries_out_none_after_it(
    sessions: list[Session], workspace: Path
) -> None:
    # Three calls: the first writes a.txt, which the test waits for; the second is a slow Grep, in
    # progress when the cancel lands; the third would write b.txt, and mustn't.
    for name, text in SLOW_FILES.items():
        (workspace / name).write_text(text, encoding="utf-8")
    calls = [
        ("t1", "Write", {"file_path": "a.txt", "content": "a"}),
        ("t2", "Grep", {"pattern": SLOW_PATTERN}),
        ("t3", "Write", {"file_path": "b.txt", "content": "b"}),
    ]
    opened = threading.Event()
    reply = tool_reply(calls)
    gated = Reply(lines=[Gate(opened), *(reply.lines or [])])
    with FakeEndpoint([gated, text_reply("never asked for")]) as fake:
        session = _session(sessions, workspace)
        session.start(fake.endpoint, effects={"write": ["*.txt"]})
        assert fake.wait_for_requests(1, REQUEST_WITHIN), "the runner never sent its request"
        opened.set()
        deadline = time.monotonic() + REQUEST_WITHIN
        while not (workspace / "a.txt").exists():
            assert time.monotonic() < deadline, "the first call was never carried out"
            time.sleep(0.005)
        started = time.monotonic()
        answer = session.request("run/cancel", {"runId": session.run_id})
        rest = session.rest()
        code = session.wait(GRACE)
        assert len(fake.requests) == 1
    assert answer["result"] == {}
    assert time.monotonic() - started < GRACE
    assert not (workspace / "b.txt").exists()
    assert all(e["type"] != "result" for e in _events([*session.received, *rest]))
    assert code == 0
    session.validate_all()


def test_shutdown_after_the_result_exits_zero_without_another_request(
    sessions: list[Session], workspace: Path
) -> None:
    with FakeEndpoint(
        [stream_error_reply("overloaded_error", "Overloaded"), text_reply("ok")]
    ) as fake:
        session = _session(sessions, workspace)
        session.start(fake.endpoint)
        events = _events(session.until_result())
        assert session.shutdown() == 0
        assert len(fake.requests) == 2
    assert [e["type"] for e in events if e["type"] == "retry"] == ["retry"]
    assert events[-1]["status"] == "ok"


def test_importing_the_runner_doesnt_import_the_library_so_the_handshake_isnt_kept_waiting() -> (
    None
):
    # The anthropic package takes about two seconds to import, more on a loaded machine: on the
    # handshake's path it made troupe's conformance checks time out at start under load. The
    # runner imports it in the worker, after run/start is answered (design D9).
    code = (
        "import sys, troupe_runner_anthropic.runner, troupe_runner_anthropic.loop; "
        "assert 'anthropic' not in sys.modules and 'httpx2' not in sys.modules, sorted(sys.modules)"
    )
    import subprocess
    import sys

    done = subprocess.run([sys.executable, "-c", code], capture_output=True, check=False)
    assert done.returncode == 0, done.stderr.decode()[-2000:]
