"""A fake LM Studio for the runner's tests (lmstudio-runner design D14).

It answers the library's greeting, and replays scripted websocket exchanges in LM Studio's own
shapes. Each websocket path (``/system``, ``/llm``) has a queue of steps: the request the client is
expected to make next (its type and endpoint), and what LM Studio answers it with. The channel or
call id in each answer is rewritten to the one the client picked. A request that isn't the next
step's is recorded as a mismatch and answered with nothing, so a test that drifts from the
recording fails on it rather than on a timeout.

Steps come from a recorded fixture (tools/capture_lm_studio.py), or are built from the recorded
shapes with the helpers here, for the cases LM Studio can't be made to show on demand. A step can
pause before an answer, or drop the connection partway, to stand in for a slow or lost LM Studio.
"""

import copy
import json
import re
import socket
import sys
import threading
import time
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import websocket

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
MODEL = "google/gemma-4-e4b"


@dataclass
class Answer:
    """One message LM Studio sends, after ``pause`` seconds."""

    message: dict[str, Any]
    pause: float = 0.0


@dataclass
class Step:
    """A request the client is expected to make next, and LM Studio's answers to it. ``drop``:
    after that many answers, the connection is dropped, as a lost LM Studio would."""

    type: str
    endpoint: str | None
    answers: list[Answer] = field(default_factory=list)
    drop: int | None = None
    greeting_after_drop: str | None = None
    """When set, the fake's greeting becomes this once the connection is dropped: "silent" or
    "not-lm-studio" for an LM Studio that stays gone, so a reconnect fails too."""


@dataclass
class Script:
    """What the fake LM Studio does: its greeting, and each path's steps."""

    steps: dict[str, deque[Step]] = field(default_factory=dict)
    greeting: str = "ok"
    """ok, redirect, not-lm-studio, or silent."""
    repeat: bool = False
    """Answer each request from the first step of its path with the same type and endpoint, and
    keep the step: for a stand-in that serves any number of runs, however each one ends (the
    conformance suite cancels some part-way), rather than a queue one run can leave out of step."""

    def add(self, path: str, steps: Iterable[Step]) -> "Script":
        self.steps.setdefault(path, deque()).extend(steps)
        return self


def load(name: str) -> list[dict[str, Any]]:
    """A recorded fixture's exchange."""
    data: list[dict[str, Any]] = json.loads(
        (FIXTURES / name / "exchange.json").read_text(encoding="utf-8")
    )
    return data


def steps_of(frames: list[dict[str, Any]]) -> list[Step]:
    """A recorded websocket's frames as steps: each client request, with LM Studio's answers up to
    the next request. The opening authentication is the fake's own, so it's left out."""
    steps: list[Step] = []
    for frame in frames:
        message = frame["message"]
        if frame["from"] == "client":
            if "authVersion" in message or message.get("type") == "channelSend":
                continue
            steps.append(Step(message["type"], message.get("endpoint")))
        elif steps and "success" not in message:
            steps[-1].answers.append(Answer(copy.deepcopy(message)))
    return steps


def script_of(name: str) -> Script:
    """A Script that replays the recorded fixture ``name``."""
    script = Script()
    for socket_ in load(name):
        script.add(socket_["path"], steps_of(socket_["frames"]))
    return script


def recorded_step(name: str, path: str, endpoint: str, index: int = 0) -> Step:
    """The ``index``th step of a recorded fixture's ``path`` with the request ``endpoint``."""
    found = [
        step
        for socket_ in load(name)
        if socket_["path"] == path
        for step in steps_of(socket_["frames"])
        if step.endpoint == endpoint
    ]
    return copy.deepcopy(found[index])


def models_step(models: list[dict[str, Any]] | None = None) -> Step:
    """The model listing: the recorded one, or ``models`` in its place."""
    step = recorded_step("two-calls", "/system", "listDownloadedModels")
    if models is not None:
        step.answers[0].message["result"] = models
    return step


def model_info(**changes: Any) -> dict[str, Any]:  # noqa: ANN401 - JSON
    """The recorded listing's entry for the model, with ``changes``."""
    info: dict[str, Any] = copy.deepcopy(models_step().answers[0].message["result"][0])
    info.update(changes)
    return info


def send(channel: int, message: dict[str, Any], pause: float = 0.0) -> Answer:
    return Answer({"type": "channelSend", "channelId": channel, "message": message}, pause)


def fragment(text: str, reasoning: str = "none") -> dict[str, Any]:
    """One fragment, in the recorded shape."""
    return {
        "type": "fragment",
        "fragment": {
            "content": text,
            "tokensCount": 1,
            "containsDrafted": False,
            "reasoningType": reasoning,
            "isStructural": reasoning in ("reasoningStartTag", "reasoningEndTag"),
            "tokens": [],
        },
    }


@dataclass
class Call:
    """A tool call a built round asks for."""

    name: str
    arguments: dict[str, Any]
    id: str = "100000001"


def predict_step(
    text: str = "",
    calls: Iterable[Call] = (),
    *,
    reasoning: str = "",
    after: str = "",
    stop: str = "eosFound",
    prompt_tokens: int = 100,
    predicted_tokens: int = 10,
    model_key: str = MODEL,
    pause: float = 0.0,
    drop: int | None = None,
    greeting_after_drop: str | None = None,
) -> Step:
    """One prediction round, built from the recorded shapes: reasoning (marked as such), then the
    answer ``text`` a word at a time, then each call's generation events, then ``after`` (text
    after the calls), then the success with its stats and model info. ``pause`` comes before every
    fragment of the answer, for a slow round."""
    answers: list[Answer] = [
        send(0, {"type": "promptProcessingProgress", "progress": 1}),
    ]
    if reasoning:
        answers.append(send(0, fragment("<|channel>thought", "reasoningStartTag")))
        answers += [send(0, fragment(word, "reasoning")) for word in _words(reasoning)]
        answers.append(send(0, fragment("<channel|>", "reasoningEndTag")))
    answers += [send(0, fragment(word), pause) for word in _words(text)]
    for call in calls:
        answers += [
            send(0, {"type": "toolCallGenerationStart", "toolCallId": call.id}),
            send(0, {"type": "toolCallGenerationNameReceived", "name": call.name}),
            send(
                0,
                {
                    "type": "toolCallGenerationEnd",
                    "toolCallRequest": {
                        "id": call.id,
                        "type": "function",
                        "arguments": call.arguments,
                        "name": call.name,
                    },
                    "rawContent": f"<|tool_call>call:{call.name}{{}}<tool_call|>",
                },
            ),
        ]
    answers += [send(0, fragment(word)) for word in _words(after)]
    success = recorded_step("two-calls", "/llm", "predict").answers
    template = next(
        a.message for a in success if a.message.get("message", {}).get("type") == "success"
    )
    done = copy.deepcopy(template)
    done["message"]["stats"].update(
        {
            "stopReason": stop,
            "promptTokensCount": prompt_tokens,
            "predictedTokensCount": predicted_tokens,
            "totalTokensCount": prompt_tokens + predicted_tokens,
        }
    )
    done["message"]["modelInfo"]["modelKey"] = model_key
    done["message"]["content"] = reasoning + text + after
    answers += [Answer(done), Answer({"type": "channelClose", "channelId": 0})]
    return Step("channelCreate", "predict", answers, drop, greeting_after_drop)


def _words(text: str) -> list[str]:
    """``text`` a word at a time, each with the space after it, as a model streams it."""
    return re.findall(r"\S+\s*|\s+", text)


def load_steps(
    context_length: int = 8192, model_key: str = MODEL, loaded: bool = True
) -> list[Step]:
    """The /llm steps that get the model and its info, from the recording, with the loaded context
    length and model key given. ``loaded=False``: LM Studio loads it first, reporting progress, in
    the shapes the library reads (startLoading, loadProgress, loadSuccess)."""
    steps = [
        recorded_step("two-calls", "/llm", "getOrLoad"),
        recorded_step("two-calls", "/llm", "getModelInfo", 0),
        recorded_step("two-calls", "/llm", "getModelInfo", 1),
    ]
    for step in steps:
        for answer in step.answers:
            message = answer.message
            info = message.get("message", {}).get("info") or message.get("result")
            if isinstance(info, dict):
                info["contextLength"] = context_length
                info["modelKey"] = model_key
    if not loaded:
        get = steps[0]
        done = next(a for a in get.answers if a.message.get("type") == "channelSend")
        done.message["message"]["type"] = "loadSuccess"
        get.answers[:0] = [
            send(0, {"type": "startLoading"}),
            send(0, {"type": "loadProgress", "progress": 0.5}),
        ]
    return steps


def listing_fails() -> Step:
    """The model listing, answered with an error, as an LM Studio that doesn't know the call
    would."""
    error = {
        "type": "rpcError",
        "callId": 0,
        "error": {"title": "Unknown endpoint listDownloadedModels"},
    }
    return Step("rpcCall", "listDownloadedModels", [Answer(error)])


def run_script(*rounds: Step, models: list[dict[str, Any]] | None = None, **load: Any) -> Script:  # noqa: ANN401
    """A Script for one run: the listing, the model got, then ``rounds``."""
    return (
        Script().add("/system", [models_step(models)]).add("/llm", [*load_steps(**load), *rounds])
    )


class FakeLMStudio:
    """The fake LM Studio, on a free local port. ``endpoint`` is its http address."""

    def __init__(self, script: Script) -> None:
        self.script = script
        self.received: list[tuple[str, dict[str, Any]]] = []
        """Every message a client sent, with the path it came on."""
        self.mismatches: list[str] = []
        self.connections: dict[str, int] = {}
        self.greetings = 0
        self._lock = threading.Lock()
        self.server = websocket.Server(self._handle)

    def __enter__(self) -> "FakeLMStudio":
        self.server.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.server.stop()

    @property
    def endpoint(self) -> str:
        return f"http://127.0.0.1:{self.server.port}"

    def drop_all(self) -> None:
        """Drop every open connection, as an LM Studio that went away would."""
        self.server.close_connections()

    def _handle(
        self, sock: socket.socket, request: str, headers: dict[str, str], rest: bytes
    ) -> None:
        path = request.split(" ")[1]
        if headers.get("upgrade", "").lower() != "websocket":
            self._greet(sock, path)
            return
        conn = websocket.server_handshake(sock, headers, rest)
        with self._lock:
            self.connections[path] = self.connections.get(path, 0) + 1
        auth = json.loads(conn.receive())
        with self._lock:
            self.received.append((path, auth))
        conn.send(json.dumps({"success": True}))
        while True:
            message = json.loads(conn.receive())
            with self._lock:
                self.received.append((path, message))
            if message.get("type") == "channelSend":
                continue
            with self._lock:
                queue = self.script.steps.get(path, deque())
                if self.script.repeat:
                    kind = (message["type"], message.get("endpoint"))
                    step = next((s for s in queue if (s.type, s.endpoint) == kind), None)
                else:
                    step = queue.popleft() if queue else None
            if step is None or (step.type, step.endpoint) != (
                message["type"],
                message.get("endpoint"),
            ):
                self.mismatches.append(
                    f"{path}: {message['type']} {message.get('endpoint')}, expected "
                    f"{step and (step.type, step.endpoint)}"
                )
                continue
            ident = {"channelId": message.get("channelId"), "callId": message.get("callId")}
            for sent, answer in enumerate(step.answers):
                if step.drop is not None and sent >= step.drop:
                    if step.greeting_after_drop is not None:
                        self.script.greeting = step.greeting_after_drop
                    sock.shutdown(socket.SHUT_RDWR)
                    return
                if answer.pause:
                    time.sleep(answer.pause)
                out = copy.deepcopy(answer.message)
                for key, value in ident.items():
                    if key in out and value is not None:
                        out[key] = value
                conn.send(json.dumps(out))

    def _greet(self, sock: socket.socket, path: str) -> None:
        with self._lock:
            self.greetings += 1
        mode = self.script.greeting
        if mode == "silent":
            time.sleep(60)
        elif mode == "redirect":
            websocket.http_answer(
                sock, "307 Temporary Redirect", b"", "Location: http://192.0.2.1:9/\r\n"
            )
        elif mode == "not-lm-studio":
            websocket.http_answer(sock, "404 Not Found", b'{"error": "no"}')
        else:
            websocket.http_answer(sock, "200 OK", b'{"lmstudio":true}')

    def sent_on(self, path: str, endpoint: str) -> list[dict[str, Any]]:
        """The requests clients made on ``path`` to ``endpoint``."""
        return [m for p, m in self.received if p == path and m.get("endpoint") == endpoint]


__all__ = [
    "MODEL",
    "Answer",
    "Call",
    "FakeLMStudio",
    "Script",
    "Step",
    "fragment",
    "listing_fails",
    "load",
    "load_steps",
    "model_info",
    "models_step",
    "predict_step",
    "recorded_step",
    "run_script",
    "script_of",
    "send",
    "steps_of",
]
