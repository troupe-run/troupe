"""With the real engine, the runner's standard output carries only the contract's messages, and the
engine's log lines go to standard error (spec: mistralrs-runner, "The protocol channel carries only
protocol messages"; in-process-runner design D3). It loads the check model the plugin carries, so no
model is downloaded; that model has no chat template, so the run itself ends with an error, which
this test doesn't look at."""

import json
from pathlib import Path

from mistralrs_harness import CHECK_MODEL, REAL, Session, run_start


def test_every_line_on_standard_output_is_a_contract_message_with_the_real_engine(
    tmp_path: Path,
) -> None:
    workspace, scratch = tmp_path / "w", tmp_path / "s"
    workspace.mkdir()
    scratch.mkdir()
    session = Session(REAL)
    try:
        assert "result" in session.initialize()
        started = session.start(run_start(workspace, scratch, str(CHECK_MODEL)))
        assert "result" in started, started
        session.until_result()
        assert session.shutdown() == 0
    finally:
        session.kill()
    for line in session.lines:
        message = json.loads(line)  # a line that isn't JSON fails here
        assert message.get("jsonrpc") == "2.0", line
    stderr = session.stderr()
    assert b"mistralrs_core" in stderr  # the engine's own log lines, moved off fd 1
    assert all(b"mistralrs_core" not in line for line in session.lines)
