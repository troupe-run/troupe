"""Whatever Ollama sends, the conversation's events keep the contract (spec: ollama-runner, "Answers
map to turns and tool calls", "Summaries fit below the event limit"; runner-protocol).

Random answers (random bytes, random JSON objects, mutated real-shaped lines, and tool calls with
random names and arguments) are fed to the conversation through a stand-in client. Every event must
validate against run-event.schema.json, fit eventMaxBytes, have each tool_result after its
tool_call, and never follow the result.
"""

import json
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from ollama_harness import validator
from test_ollama_conversation import Recorder
from troupe_plugin_sdk import runner as p
from troupe_plugin_sdk.events import encoded_size
from troupe_runner_ollama.client import EngineError, RetryableError
from troupe_runner_ollama.conversation import Conversation
from troupe_runner_ollama.options import Options

EVENT_MAX_BYTES = 2048
EVENTS = validator("run-event.schema.json#/properties/params")

_JSON = st.recursive(
    st.none() | st.booleans() | st.integers() | st.floats(allow_nan=False) | st.text(max_size=20),
    lambda children: (
        st.lists(children, max_size=3) | st.dictionaries(st.text(max_size=8), children, max_size=3)
    ),
    max_leaves=6,
)
_TOOLS = st.sampled_from(["Read", "Write", "Edit", "Glob", "Grep", "Delete", "Move", "Bash", ""])
_CALL = st.fixed_dictionaries(
    {
        "function": st.fixed_dictionaries(
            {},
            optional={
                "name": _TOOLS | _JSON,
                "arguments": st.fixed_dictionaries(
                    {}, optional={"file_path": st.text(max_size=12), "pattern": st.text(max_size=6)}
                )
                | st.text(max_size=30)
                | _JSON,
                "index": st.integers(0, 3),
            },
        )
    },
    optional={"id": st.text(max_size=6) | _JSON},
)
_MESSAGE = st.fixed_dictionaries(
    {},
    optional={
        "role": st.just("assistant"),
        "content": st.text(max_size=3000) | _JSON,
        "thinking": st.text(max_size=50) | _JSON,
        "tool_calls": st.lists(_CALL, max_size=3) | _JSON,
    },
)
_LINE = st.fixed_dictionaries(
    {"message": _MESSAGE},
    optional={
        "done": st.booleans() | _JSON,
        "done_reason": st.sampled_from(["stop", "length"]) | _JSON,
        "prompt_eval_count": st.integers(-5, 10**6) | _JSON,
        "eval_count": st.integers(-5, 10**6) | _JSON,
        "error": st.text(max_size=20),
    },
)
_RAW = st.binary(max_size=40) | _LINE.map(lambda line: json.dumps(line).encode())
_DONE = json.dumps({"message": {"content": ""}, "done": True}).encode()
_ANSWER = st.lists(_RAW, max_size=6).map(lambda lines: [*lines, _DONE])
_STATUS = st.sampled_from([None, None, None, 400, 503])


class _ScriptedClient:
    """Plays answers in turn: lines, or a failure the real client would raise."""

    def __init__(self, answers: list[list[bytes] | int]) -> None:
        self._answers = answers

    def chat(self, body: bytes) -> Iterator[bytes]:
        json.loads(body)  # every request is JSON
        if not self._answers:
            yield json.dumps({"message": {"content": "end"}, "done": True}).encode()
            return
        answer = self._answers.pop(0)
        if answer == 400:
            raise EngineError(400, "Ollama answered refused", b"{}")
        if answer == 503:
            raise RetryableError("server", "busy", b"{}")
        assert isinstance(answer, list)
        yield from answer


@settings(max_examples=150, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(answers=st.lists(_STATUS.flatmap(lambda s: st.just(s) if s else _ANSWER), max_size=5))
def test_any_answers_give_events_that_keep_the_contract(
    tmp_path: Path, answers: list[list[bytes] | int]
) -> None:
    workspace = tmp_path / str(uuid.uuid4())
    workspace.mkdir()
    scratch = tmp_path / f"{workspace.name}-scratch"
    scratch.mkdir()
    sink = Recorder()
    start = p.RunStartParams(
        run_id=str(uuid.uuid4()),
        direction="d",
        workspace=str(workspace),
        options={},
        limits=p.StartLimits(event_max_bytes=EVENT_MAX_BYTES),
        effects=p.EffectsDeclaration(write=["**"], delete=[], move=[]),
        scratch=str(scratch),
    )
    Conversation(
        start=start,
        options=Options(model="m", max_turns=4),
        window=4096,
        engine_version="0.40.14",
        client=_ScriptedClient(list(answers)),  # type: ignore[arg-type]
        sink=sink,
    ).run()
    events: list[dict[str, Any]] = [event.to_data() for event in sink.events]
    assert [event["seq"] for event in events] == list(range(len(events)))
    assert events[-1]["type"] == "result"
    calls: set[str] = set()
    for event in events:
        assert EVENTS.is_valid(event), event
        assert encoded_size(event) <= EVENT_MAX_BYTES
        if event["type"] == "tool_call":
            calls.add(event["callId"])
        if event["type"] == "tool_result":
            assert event["callId"] in calls
    assert [event["type"] for event in events].count("result") == 1
