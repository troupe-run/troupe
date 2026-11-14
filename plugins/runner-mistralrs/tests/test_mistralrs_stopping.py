"""Cancel, end of input and shutdown end the runner's process at once, whatever the engine is doing
(spec: mistralrs-runner, "Cancel and end of input end the process at once", "The model loads after
the run is acknowledged, within a named limit"; in-process-runner design D2).

The stand-in holds a request or a load open the way the engine does, blocked with the GIL
released and nothing to interrupt. The real engine is stopped while it loads and answers with the
check model; a real model mid-answer is the live test's.
"""

import os
import time
from pathlib import Path
from typing import Any

import pytest

from mistralrs_harness import CHECK_MODEL, REAL, STAND_IN, Session, run_start
from stand_in import write_script
from troupe_runner_mistralrs.defaults import STOP_GRACE_SECONDS

GRACE = STOP_GRACE_SECONDS + 3.0
"""How long a test lets the process take to exit: the runner's own grace, and a margin for a
loaded CI machine. Well under troupe's 10 s."""

HELD = 60
"""Seconds the stand-in holds a request or a load: far past any grace, so only exiting ends it."""


@pytest.fixture
def dirs(tmp_path: Path) -> tuple[Path, Path]:
    workspace, scratch = tmp_path / "w", tmp_path / "s"
    workspace.mkdir()
    scratch.mkdir()
    return workspace, scratch


def _stand_in(tmp_path: Path, script: dict[str, Any]) -> Session:
    path = write_script(tmp_path / "script.json", script)
    return Session(STAND_IN, env={**os.environ, "TROUPE_MISTRALRS_STAND_IN": str(path)})


def _until(session: Session, method: str, kind: str | None = None) -> None:
    """Read until a ``method`` message (of ``kind``, for a transcript record)."""
    while True:
        message = session.read()
        assert message is not None, f"the runner ended before {method}"
        if message.get("method") == method and kind in (None, message["params"].get("kind")):
            return


def _exits_within_grace(session: Session) -> float:
    began = time.monotonic()
    code = session.process.wait(GRACE)
    took = time.monotonic() - began
    assert code == 0
    return took


def test_cancel_while_the_engine_holds_a_request_acknowledges_and_exits(
    tmp_path: Path, dirs: tuple[Path, Path]
) -> None:
    session = _stand_in(tmp_path, {"responses": [{"sleep": HELD}]})
    try:
        session.initialize()
        session.start(run_start(*dirs, str(CHECK_MODEL)))
        _until(session, "run/transcript", "sent")  # the request is in flight
        session.send({"jsonrpc": "2.0", "id": 9, "method": "run/cancel", "params": {}})
        assert session.read() == {"jsonrpc": "2.0", "id": 9, "result": {}}
        assert session.read() is None  # no event follows the acknowledgement
        _exits_within_grace(session)
    finally:
        session.kill()


def test_end_of_input_while_the_engine_holds_a_request_exits(
    tmp_path: Path, dirs: tuple[Path, Path]
) -> None:
    session = _stand_in(tmp_path, {"responses": [{"sleep": HELD}]})
    try:
        session.initialize()
        session.start(run_start(*dirs, str(CHECK_MODEL)))
        _until(session, "run/transcript", "sent")
        session.close_input()
        assert session.read() is None
        _exits_within_grace(session)
    finally:
        session.kill()


def test_end_of_input_during_the_load_exits_with_no_further_event(
    tmp_path: Path, dirs: tuple[Path, Path]
) -> None:
    session = _stand_in(tmp_path, {"load": {"sleep": HELD}})
    try:
        session.initialize()
        session.start(run_start(*dirs, str(CHECK_MODEL)))
        _until(session, "run/event")  # init
        _until(session, "run/event")  # the log saying it loads
        session.close_input()
        assert session.read() is None
        _exits_within_grace(session)
    finally:
        session.kill()


def test_shutdown_while_the_engine_holds_a_request_answers_and_exits(
    tmp_path: Path, dirs: tuple[Path, Path]
) -> None:
    session = _stand_in(tmp_path, {"responses": [{"sleep": HELD}]})
    try:
        session.initialize()
        session.start(run_start(*dirs, str(CHECK_MODEL)))
        _until(session, "run/transcript", "sent")
        session.send({"jsonrpc": "2.0", "id": 9, "method": "shutdown", "params": {}})
        assert session.read() == {"jsonrpc": "2.0", "id": 9, "result": {}}
        _exits_within_grace(session)
    finally:
        session.kill()


@pytest.mark.parametrize("how", ["cancel", "end of input"])
def test_the_real_engine_is_left_behind_on_cancel_or_end_of_input(
    dirs: tuple[Path, Path], how: str
) -> None:
    session = Session(REAL)
    try:
        session.initialize()
        session.start(run_start(*dirs, str(CHECK_MODEL)))
        if how == "cancel":
            session.send({"jsonrpc": "2.0", "id": 9, "method": "run/cancel", "params": {}})
        else:
            session.close_input()
        _exits_within_grace(session)
    finally:
        session.kill()
