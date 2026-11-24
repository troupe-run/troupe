"""How the runner writes a message: a lone surrogate in it is written as U+FFFD, and the runner says
on standard error how many it replaced (spec: anthropic-runner; host-robustness design D3).

Its tests that start a process, open a socket or use a git theatre are in
integration/test_anthropic_runner.py."""

import io
import json

from troupe_plugin_sdk import runner as p
from troupe_runner_anthropic.runner import Runner

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
