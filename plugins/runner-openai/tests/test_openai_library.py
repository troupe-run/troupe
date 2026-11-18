"""What must hold whichever HTTP stack sends the runner's requests (openai-library design D11): the
runner as troupe runs it, against the fake endpoint. Written before the runner moved onto the openai
package, and passing on the runner as it was, so each one shows a behaviour the move kept (spec:
openai-runner, "The library finds nothing of its own", "The library's own logging stays out of the
run's output", "The runner talks to its service only through the openai package")."""

import io
import json
import logging
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from fake_endpoint import FakeEndpoint, Reply, final, function_call, sse, text_reply, usage
from openai_harness import CANARY, Session
from troupe_runner_openai.defaults import LIBRARY_LOG_MAX_BYTES
from troupe_runner_openai.failures import StatusError
from troupe_runner_openai.library import clear_library_environment, quiet_library_logging

FIRST_REQUEST = Path(__file__).parent / "data" / "first-request.json"
"""The body of a run's first request as the runner sent it over urllib, before the openai package
(openai-library design D1): the run below, with the direction, character and model it names."""

LIBRARY_VARIABLES = {
    "OPENAI_API_KEY": "sk-from-the-environment",
    "OPENAI_ADMIN_KEY": "sk-admin-from-the-environment",
    "OPENAI_BASE_URL": "http://127.0.0.1:9/v1",
    "OPENAI_ORG_ID": "org-from-the-environment",
    "OPENAI_PROJECT_ID": "proj-from-the-environment",
    "OPENAI_CUSTOM_HEADERS": "X-From-The-Environment: yes\nAuthorization: Bearer sk-custom",
}
"""Every variable the openai package reads when it isn't given what it names."""


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


def _run(
    sessions: list[Session],
    workspace: Path,
    replies: list[Reply],
    credential: str | None,
    env: dict[str, str] | None = None,
    **start: Any,  # noqa: ANN401
) -> tuple[Session, FakeEndpoint, list[dict[str, Any]]]:
    with FakeEndpoint(replies) as fake:
        session = Session(workspace, credential, env)
        sessions.append(session)
        session.start(fake.endpoint, **start)
        messages = session.until_result()
        assert session.shutdown() == 0
    return session, fake, [m["params"] for m in messages if m.get("method") == "run/event"]


def test_variables_the_library_reads_change_nothing_without_a_credential(
    sessions: list[Session], workspace: Path
) -> None:
    _, fake, events = _run(sessions, workspace, [text_reply("Done.")], None, LIBRARY_VARIABLES)
    assert events[-1]["status"] == "ok"
    assert len(fake.requests) == 1
    headers = fake.requests[0].headers
    named = ("authorization", "openai-organization", "openai-project", "x-from-the-environment")
    for name in named:
        assert name not in headers


def test_a_runtime_credential_wins_over_the_variable(
    sessions: list[Session], workspace: Path
) -> None:
    _, fake, _ = _run(sessions, workspace, [text_reply("Done.")], CANARY, LIBRARY_VARIABLES)
    assert [r.headers.get("authorization") for r in fake.requests] == [f"Bearer {CANARY}"]
    assert "openai-organization" not in fake.requests[0].headers


def test_debug_logging_asked_for_keeps_standard_output_to_the_protocol_and_headers_off_stderr(
    sessions: list[Session], workspace: Path
) -> None:
    session, _, events = _run(
        sessions, workspace, [text_reply("Done.")], CANARY, {"OPENAI_LOG": "debug"}
    )
    assert events[-1]["status"] == "ok"
    for line in session.raw:
        assert json.loads(line)["jsonrpc"] == "2.0"
    stderr = session.stderr().lower()
    assert b"authorization" not in stderr
    assert CANARY.encode() not in stderr


def test_the_first_request_is_the_body_the_runner_sent_before_the_library(
    sessions: list[Session], workspace: Path
) -> None:
    session, fake, _ = _run(
        sessions,
        workspace,
        [text_reply("Done.")],
        CANARY,
        model="gpt-test",
        direction="Write out/hello.txt",
        character="You are terse.",
    )
    request = fake.requests[0]
    assert (request.method, request.path) == ("POST", "/v1/responses")
    # The tools' descriptions name the run's scratch directory, which differs per run.
    sent = json.loads(request.body.decode("utf-8").replace(_escaped(session.scratch()), SCRATCH))
    assert sent == json.loads(FIRST_REQUEST.read_text(encoding="utf-8"))


SCRATCH = "<scratch>"
"""What the recorded first request holds where the run's scratch directory was."""


def _escaped(path: Path) -> str:
    """``path`` as it appears inside a JSON string."""
    return json.dumps(str(path))[1:-1]


def test_a_byte_that_isnt_utf_8_in_the_stream_is_retried_as_network(
    sessions: list[Session], workspace: Path
) -> None:
    broken = Reply(chunks=[b'data: {"type": "response.created", "x": "\xff"}\n\n'])
    _, fake, events = _run(sessions, workspace, [broken, text_reply("Done.")], CANARY)
    assert [e["reason"] for e in events if e["type"] == "retry"] == ["network"]
    assert events[-1]["status"] == "ok"
    assert len(fake.requests) == 2


def test_the_transcript_receives_each_event_as_json_not_each_line(
    sessions: list[Session], workspace: Path
) -> None:
    """Fails on the runner before the openai package, which recorded each stream line, event:
    and blank lines included: the transcript now keeps what the library exposes (openai-library
    design D6; spec: openai-runner, "The transcript is what the library exposes")."""
    session, _, _ = _run(sessions, workspace, [text_reply("Done.")], CANARY)
    records = [m["params"] for m in session.received if m.get("method") == "run/transcript"]
    kinds = [r["kind"] for r in records]
    assert kinds[:2] == ["sent", "note"]
    received = [json.loads(r["record"]) for r in records if r["kind"] == "received"]
    assert [e["type"] for e in received] == [
        "response.created",
        "response.output_text.delta",
        "response.completed",
    ]


# What the runner sets around the library (library.py, failures.py)


def test_every_variable_the_library_reads_is_removed_and_nothing_else() -> None:
    environ = {**LIBRARY_VARIABLES, "OPENAI_LOG": "debug", "HTTPS_PROXY": "http://p:1", "PATH": "x"}
    removed = clear_library_environment(environ)
    assert removed == sorted([*LIBRARY_VARIABLES, "OPENAI_LOG"])
    assert environ == {"HTTPS_PROXY": "http://p:1", "PATH": "x"}


def test_the_librarys_warnings_reach_standard_error_masked_and_cut_and_nothing_below() -> None:
    out = io.StringIO()
    quiet_library_logging(lambda text: text.replace(CANARY, "[credential]"), out)
    logger = logging.getLogger("openai")
    logger.debug("Request options: Authorization: Bearer %s", CANARY)
    logger.info("HTTP Request: POST")
    logger.warning("retrying with %s and %s", CANARY, "x" * (LIBRARY_LOG_MAX_BYTES * 2))
    written = out.getvalue()
    assert written.count("\n") == 1
    assert written.startswith("openai runner: library warning: retrying with [credential]")
    assert written.rstrip().endswith("bytes left out)")
    assert CANARY not in written
    assert "Authorization" not in written


def test_a_status_failure_keeps_its_headers_by_lower_case_name() -> None:
    failure = StatusError(429, {"Retry-After": "2"}, b"{}")
    assert failure.headers == {"retry-after": "2"}


def test_a_wrong_shaped_response_ends_the_run_with_no_serialiser_warning_on_stderr(
    sessions: list[Session], workspace: Path
) -> None:
    """Spec: openai-runner, "The library's own logging stays out of the run's output", "A
    wrong-shaped response": the library's models serialise a field of the wrong type with a
    warning per field unless told not to (review of #440)."""
    done = final([function_call("c1", "Write", "{}")], used=usage(100, 10))
    done["response"]["output"][0]["arguments"] = {"file_path": "a.txt"}
    done["response"]["usage"]["input_tokens_details"]["cached_tokens"] = "40"
    session, _, events = _run(sessions, workspace, [Reply(lines=sse([done]))], CANARY)
    result = events[-1]
    assert (result["status"], result["reason"]) == ("error", "engine")
    stderr = session.stderr()
    assert b"Warning" not in stderr
    assert b"PydanticSerializationUnexpectedValue" not in stderr


def test_loading_the_runner_leaves_the_library_unloaded() -> None:
    """openai-library design D8, D9: the library is imported in the worker, after OPENAI_LOG is
    cleared, never as the runner loads (review of #440)."""
    probe = (
        "import sys, troupe_runner_openai.runner, troupe_runner_openai.runtime; "
        "print(sorted(m for m in sys.modules if m.split('.')[0] in ('openai', 'httpx2')))"
    )
    done = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=True, timeout=60
    )
    assert done.stdout.strip() == "[]"
