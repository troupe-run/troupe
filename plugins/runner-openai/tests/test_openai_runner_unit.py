"""The test harness refuses a run started on the real use limits unless a test gives its reason
(design D7), and the runner writes a lone surrogate in a message as U+FFFD, with the count on
standard error (spec: openai-runner; host-robustness design D3).

Its tests that start a process, open a socket or use a git theatre are in
integration/test_openai_runner.py."""

import io
import json

import pytest

from openai_harness import (
    TEST_LIMITS,
    LimitsNotSetError,
    check_limits,
)
from troupe_plugin_sdk import runner as p
from troupe_runner_openai.runner import Runner

# The test limits


def test_a_run_started_on_the_real_use_limits_is_refused_by_the_harness() -> None:
    with pytest.raises(LimitsNotSetError):
        check_limits({}, None)
    check_limits(TEST_LIMITS, None)
    check_limits({"maxTurns": 3}, None)
    check_limits({}, "refused before any request")


# Requirement: A message's strings are Unicode text (host-robustness design D3)


def test_a_lone_surrogate_in_a_message_is_written_as_the_replacement_character() -> None:
    # An engine's \ud800 escape decodes to a lone surrogate, which the host refuses (#311).
    stdout, stderr = io.BytesIO(), io.BytesIO()
    writer = Runner(io.BytesIO(), stdout, stderr)
    writer._write({"jsonrpc": "2.0", "method": "run/event", "params": {"x\udfff": "a\ud800b"}})
    message = json.loads(stdout.getvalue())
    assert message["params"] == {"x\ufffd": "a\ufffdb"}
    assert p.lone_surrogate(message) is None
    assert b"2 lone surrogates in a run/event message were written as U+FFFD" in stderr.getvalue()
