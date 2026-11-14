"""The runner with a real model, run only when TROUPE_LIVE_MISTRALRS names a GGUF file (spec:
mistralrs-runner, "Tests load no downloaded model", "Cancel and end of input end the process at
once"; in-process-runner design D10). CI never sets it: no model is downloaded there.

    TROUPE_LIVE_MISTRALRS=/path/to/Qwen3-0.6B-Q8_0.gguf uv run pytest plugins/runner-mistralrs
"""

import os
import time
from pathlib import Path

import pytest

from mistralrs_harness import REAL, Session, events, run_start
from troupe_runner_mistralrs.defaults import STOP_GRACE_SECONDS

MODEL = os.environ.get("TROUPE_LIVE_MISTRALRS", "")

pytestmark = pytest.mark.skipif(
    not MODEL, reason="set TROUPE_LIVE_MISTRALRS to a GGUF model file to run the live tests"
)

OPTIONS = {"temperature": 0, "think": False, "seed": 7, "maxTurns": 5}


@pytest.fixture
def dirs(tmp_path: Path) -> tuple[Path, Path]:
    workspace, scratch = tmp_path / "w", tmp_path / "s"
    workspace.mkdir()
    scratch.mkdir()
    (workspace / "notes.txt").write_text("The launch code is BLUE-42.\n", encoding="utf-8")
    return workspace, scratch


def test_a_real_model_reads_a_file_with_a_tool_and_answers(dirs: tuple[Path, Path]) -> None:
    session = Session(REAL)
    try:
        session.initialize()
        params = run_start(
            *dirs,
            MODEL,
            direction="Call the Read tool with file_path notes.txt (a path relative to the "
            "workspace), then tell me the launch code it gives.",
            options=OPTIONS,
        )
        assert "result" in session.start(params)
        seen = events(session.until_result())
        assert session.shutdown() == 0
    finally:
        session.kill()
    assert [e["tool"] for e in seen if e["type"] == "tool_call"] == ["Read"]
    assert seen[-1]["status"] == "ok"
    assert "BLUE-42" in seen[-1]["message"]


def test_cancel_while_a_real_model_generates_exits_within_the_grace(
    dirs: tuple[Path, Path],
) -> None:
    session = Session(REAL)
    try:
        session.initialize()
        params = run_start(
            *dirs,
            MODEL,
            direction="Write a story of at least two thousand words about a lighthouse keeper.",
            options=OPTIONS,
        )
        assert "result" in session.start(params)
        while True:  # until the request is in flight
            message = session.read()
            assert message is not None
            if message.get("method") == "run/transcript":
                break
        time.sleep(2)  # the model is generating
        session.send({"jsonrpc": "2.0", "id": 9, "method": "run/cancel", "params": {}})
        assert session.read() == {"jsonrpc": "2.0", "id": 9, "result": {}}
        began = time.monotonic()
        assert session.process.wait(STOP_GRACE_SECONDS + 3) == 0
        assert time.monotonic() - began < STOP_GRACE_SECONDS + 3
    finally:
        session.kill()
