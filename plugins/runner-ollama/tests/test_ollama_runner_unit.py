"""The Ollama runner driven in this process over in-memory streams: a failure of the runner itself
is reported, and the runner answers and exits 1, also when its input ends after the failure, and
a lone surrogate in a message is written as U+FFFD with the count on standard error (spec:
ollama-runner, runner-protocol; host-robustness design D3).

Its tests that start a process, open a socket or use a git theatre are in
integration/test_ollama_runner.py."""

import io
import json

import pytest

from troupe_plugin_sdk import runner as p
from troupe_runner_ollama.runner import Runner, _Exit


class _Exploding:
    """A conversation that fails as a bug in the runner would."""

    def __init__(self) -> None:
        self.failed_with: str | None = None

    def run(self) -> None:
        raise KeyError("boom")

    def fail(self, message: str) -> None:
        self.failed_with = message


def test_a_failure_of_the_runner_itself_is_reported_and_its_exit_is_1() -> None:
    stdout, stderr = io.BytesIO(), io.BytesIO()
    runner = Runner(io.BytesIO(), stdout, stderr)
    conversation = _Exploding()
    runner._converse(conversation)  # type: ignore[arg-type]
    assert conversation.failed_with == "The Ollama runner failed: KeyError: 'boom'"
    assert b"the conversation failed" in stderr.getvalue()
    assert b"KeyError" in stderr.getvalue()
    with pytest.raises(_Exit) as exited:
        runner._end(1, None)
    assert exited.value.code == 1
    assert json.loads(stdout.getvalue().splitlines()[-1]) == {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {},
    }


def test_end_of_input_after_the_runner_failed_exits_1() -> None:
    stdout, stderr = io.BytesIO(), io.BytesIO()
    runner = Runner(io.BytesIO(), stdout, stderr)
    runner._converse(_Exploding())  # type: ignore[arg-type]
    assert runner.run() == 1  # its standard input is already at its end


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
