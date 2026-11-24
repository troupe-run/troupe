"""The harness's check for a stand-in claude left running, which passes when no record was written
and fails naming a record that names no pid, and how the runner writes a message: a lone
surrogate in it is written as U+FFFD, with the count on standard error (spec: claude-code-runner;
host-robustness design D3).

Its tests that start a process, open a socket or use a git theatre are in
integration/test_claude_code_runner.py."""

import io
import json
from pathlib import Path

import pytest

from claude_harness import (
    stand_in_left_running,
)
from troupe_plugin_sdk import runner as p
from troupe_runner_claude_code.runner import Runner


def test_the_check_passes_when_no_stand_in_wrote_a_record(tmp_path: Path) -> None:
    assert stand_in_left_running(str(tmp_path / "never-written.json")) is None
    assert stand_in_left_running(None) is None


@pytest.mark.parametrize("text", ["", "{}", '{"pid": "x"}', "[1]", "not json"])
def test_a_record_that_names_no_pid_is_an_error_naming_it(tmp_path: Path, text: str) -> None:
    record = tmp_path / "record.json"
    record.write_text(text, encoding="utf-8")
    with pytest.raises(AssertionError, match="names no pid"):
        stand_in_left_running(str(record))


# Requirement: A message's strings are Unicode text (host-robustness design D3)


def test_a_lone_surrogate_in_a_message_is_written_as_the_replacement_character() -> None:
    # An engine's \ud800 escape decodes to a lone surrogate, which the host refuses (#311).
    stdout, stderr = io.BytesIO(), io.BytesIO()
    writer = Runner(io.BytesIO(), stdout, stderr)
    writer._send({"jsonrpc": "2.0", "method": "run/event", "params": {"x\udfff": "a\ud800b"}})
    message = json.loads(stdout.getvalue())
    assert message["params"] == {"x\ufffd": "a\ufffdb"}
    assert p.lone_surrogate(message) is None
    assert b"2 lone surrogates in a run/event message were written as U+FFFD" in stderr.getvalue()
