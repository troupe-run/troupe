"""A stand-in for the engine: it serves recorded responses, in order, and records each request
(in-process-runner design D10). Responses are in the form engine.serialised writes, as the
fixtures hold them, so a fixture replays exactly what the real engine returned.

A script says what the stand-in does:

- ``responses``: each a serialised response, or ``{"error": "<the engine's words>"}`` to fail
  that request as the engine would, or ``{"sleep": seconds}`` to hold the request that long (with
  the GIL released, as the engine does) before failing it. A serialised response may hold
  ``delay``, seconds to wait before answering.
- ``maxSequenceLength``: the model's length, or null. Default 40960.
- ``load``: ``"ok"``, ``{"error": "<words>"}``, or ``{"sleep": seconds}`` to hold the load.
- ``check``: ``"ok"`` or ``{"error": "<words>"}``, for the platform check.
- ``tokensPerChar``: how the stand-in counts tokens. Default 0.25.
- ``counts``: recorded token counts by the SHA-256 of the text, which win over ``tokensPerChar``,
  so a fixture counts as the real run did. ``paths`` maps each placeholder (``<workspace>``,
  ``<scratch>``) to this run's path, put back in placeholders before hashing.
"""

import hashlib
import json
import math
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from troupe_runner_mistralrs.port import (
    Answer,
    ChatRequest,
    EngineFailure,
    LoadSpec,
    ToolCall,
)

VERSION = "0.9.5"


def answer_from_record(record: Mapping[str, Any]) -> Answer:
    """The runner's view of a serialised response, as engine.answer_of makes one."""
    choice = record["choices"][0]
    message = choice["message"]
    usage = record.get("usage", {})
    return Answer(
        content=message.get("content") or "",
        reasoning=message.get("reasoning_content") or "",
        tool_calls=[
            ToolCall(call["id"], call["function"]["name"], call["function"]["arguments"])
            for call in message.get("tool_calls") or []
        ],
        finish_reason=choice["finish_reason"],
        prompt_tokens=usage.get("prompt_tokens"),
        completion_tokens=usage.get("completion_tokens"),
        record=record,
    )


class StandInEngine:
    def __init__(self, script: Mapping[str, Any], spec: LoadSpec) -> None:
        self.script = script
        self.spec = spec
        self.requests: list[ChatRequest] = []
        self._responses = list(script.get("responses", []))

    @property
    def version(self) -> str:
        return VERSION

    def max_sequence_length(self) -> int | None:
        value = self.script.get("maxSequenceLength", 40960)
        return value if isinstance(value, int) else None

    def count(self, text: str) -> int:
        named = text
        for placeholder, path in self.script.get("paths", {}).items():
            named = named.replace(path, placeholder)
        recorded = self.script.get("counts", {}).get(
            hashlib.sha256(named.encode("utf-8")).hexdigest()
        )
        if isinstance(recorded, int):
            return recorded
        return math.ceil(len(text) * float(self.script.get("tokensPerChar", 0.25)))

    def chat(self, request: ChatRequest) -> Answer:
        self.requests.append(request)
        if not self._responses:
            raise EngineFailure("the stand-in has no more responses")
        response = self._responses.pop(0)
        if "sleep" in response:
            time.sleep(float(response["sleep"]))
            raise EngineFailure("the stand-in slept through its request")
        if "error" in response:
            raise EngineFailure(str(response["error"]))
        time.sleep(float(response.pop("delay", 0)))
        return answer_from_record(response)


class StandIn:
    """The loader and the platform check, from a script."""

    def __init__(self, script: Mapping[str, Any]) -> None:
        self.script = script
        self.engines: list[StandInEngine] = []

    def load(self, spec: LoadSpec) -> StandInEngine:
        load = self.script.get("load", "ok")
        if isinstance(load, Mapping) and "sleep" in load:
            time.sleep(float(load["sleep"]))
        if isinstance(load, Mapping) and "error" in load:
            raise EngineFailure(str(load["error"]))
        engine = StandInEngine(self.script, spec)
        self.engines.append(engine)
        return engine

    def check(self) -> None:
        check = self.script.get("check", "ok")
        if isinstance(check, Mapping) and "error" in check:
            raise EngineFailure(str(check["error"]))


def response(
    content: str = "",
    *,
    calls: Sequence[tuple[str, str, Any]] = (),
    finish: str = "stop",
    prompt: int = 100,
    completion: int = 10,
    reasoning: str | None = None,
) -> dict[str, Any]:
    """A serialised response, in engine.serialised's form."""
    message: dict[str, Any] = {"role": "assistant", "content": content}
    if reasoning is not None:
        message["reasoning_content"] = reasoning
    if calls:
        message["tool_calls"] = [
            {
                "id": call_id,
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": arguments if isinstance(arguments, str) else json.dumps(arguments),
                },
            }
            for call_id, name, arguments in calls
        ]
    return {
        "id": "1",
        "object": "chat.completion",
        "created": 0,
        "model": "mistralrs",
        "system_fingerprint": "local",
        "choices": [{"index": 0, "finish_reason": finish, "message": message}],
        "usage": {
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "total_tokens": prompt + completion,
        },
    }


def write_script(path: Path, script: Mapping[str, Any]) -> Path:
    path.write_text(json.dumps(script), encoding="utf-8")
    return path
