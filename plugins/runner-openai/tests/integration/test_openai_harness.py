"""The harness itself: what it reads from the runner, whatever order the runner writes it in
(request-keeps-notifications design D1, #392)."""

import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from fake_endpoint import FakeEndpoint, text_reply
from openai_harness import CANARY, TIMEOUT, Session

POLL_SECONDS = 0.01


@pytest.fixture
def session(tmp_path: Path) -> Iterator[Session]:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    started = Session(workspace, CANARY)
    yield started
    started.kill()


def _written(session: Session, marker: bytes, within: float) -> bool:
    """Whether the runner has written a line holding ``marker``, waiting up to ``within``
    seconds. It reads ``raw``, which the reader fills as lines arrive, so nothing is taken off
    the stream the test then reads."""
    deadline = time.monotonic() + within
    while time.monotonic() < deadline:
        if any(marker in line for line in list(session.raw)):
            return True
        time.sleep(POLL_SECONDS)
    return False


def test_a_result_written_before_a_requests_answer_is_still_read_by_until_result(
    session: Session,
) -> None:
    with FakeEndpoint([text_reply("Done.")]) as fake:
        session.start(fake.endpoint)
        assert _written(session, b'"type":"result"', TIMEOUT), "the run never wrote its result"
        second = session.request("run/start", session.sent[-1]["params"])
        messages = session.until_result()
    assert second["error"]["data"]["code"] == "runner.already-started"
    result = messages[-1]["params"]
    assert (result["type"], result["status"]) == ("result", "ok")
