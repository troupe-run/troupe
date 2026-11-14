"""One run's conversation with the in-process engine: troupe's own tool loop (in-process-runner
design D6 to D9).

The conversation loads the model through a ``Loader``, builds each request, carries out the model's
tool calls with the plugin SDK's ``Tools``, and reports the run through a ``Sink``: run events,
transcript records, and whether the run is stopping. It holds the conversation itself, so it records
what it adds to it as well as what the engine answers.

The context window is the runner's to keep (design D7): before each request it counts the
conversation with the model's tokenizer and asks for at most the room left, so an answer can't run
past the window on any OS, whether or not the engine caps its KV cache. Nothing is retried: every
failure in process is deterministic.

It starts no process. The runner runs it on a worker thread, and stops it by ending the process: an
engine call can't be interrupted (design D2). The sink drops everything once the run is stopping.
"""

import json
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from troupe_plugin_sdk import runner as p
from troupe_plugin_sdk.compaction import Candidate, choose, stub
from troupe_plugin_sdk.declaration import Declaration
from troupe_plugin_sdk.defaults import (
    BYTES_PER_TOKEN,
    COMPACT_AT_SHARE,
    COMPACT_TO_SHARE,
    GLOB_MAX_PATHS,
    GREP_MAX_MATCHES,
    READ_MAX_BYTES,
    ToolLimits,
)
from troupe_plugin_sdk.events import EventNumbering, context_event, cut, fit, utf8_size
from troupe_plugin_sdk.tools import Tools
from troupe_runner_mistralrs import NAME, __version__
from troupe_runner_mistralrs.defaults import (
    DEFAULT_CONTEXT_LENGTH,
    GLOB_PATH_BYTES,
    GREP_MATCH_BYTES,
    LOAD_TIMEOUT_SECONDS,
    MESSAGE_OVERHEAD_TOKENS,
    READ_NOTE_BYTES,
    SUMMARY_MAX_BYTES,
    TOKEN_MARGIN,
    TOOL_OUTPUT_SHARE,
    TOOLS_OVERHEAD_TOKENS,
)
from troupe_runner_mistralrs.options import Options
from troupe_runner_mistralrs.port import (
    Answer,
    ChatRequest,
    Engine,
    EngineFailure,
    Loader,
    LoadSpec,
)

NO_TEXT = "(no text)"
"""The ok result's message when the model's last answer had no text."""

ENGINE_NAME = "mistral.rs"
"""The engine, as the init event names it."""


class Sink(Protocol):
    """Where the conversation sends what it reports, and how it learns the run is stopping."""

    def event(self, event: p.RunEvent) -> None: ...

    def transcript(self, kind: p.TranscriptKind, record: bytes) -> None:
        """One transcript record and its kind: ``sent`` for what the runner passed the engine,
        ``received`` for what the engine returned."""
        ...

    def stopping(self) -> bool:
        """Whether the run is stopping: no further request, tool call or event."""
        ...


class _Stop(Exception):  # noqa: N818 - a signal to stop, not an error
    """The run is stopping: send nothing more."""


@dataclass
class _RunEnded(Exception):  # noqa: N818 - an ending, not an error of the runner's
    """The run ends with an error result holding ``message``, for ``reason``."""

    message: str
    reason: p.FailureReason


@dataclass
class _Full(Exception):  # noqa: N818 - the window is full, which a run told compact may get past
    """The conversation, or the answer, reached the run's window: ``message`` says how."""

    message: str


@dataclass
class _ToolResult:
    """A ``tool`` message in the conversation, for compaction (compaction-opt-in design D4)."""

    index: int
    """Its position in the conversation's messages."""
    tool: str
    call_id: str
    size: int
    turn: int
    stubbed: bool = False


def encode(value: object) -> bytes:
    """The bytes a JSON value is recorded as: compact, UTF-8, the same everywhere."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8", "backslashreplace"
    )


def tool_budget(window: int) -> int:
    """The UTF-8 bytes one tool result may take, for a context window of ``window`` tokens."""
    return max(1, int(window * TOOL_OUTPUT_SHARE) * BYTES_PER_TOKEN)


def tool_limits(window: int) -> ToolLimits:
    """The SDK's tool limits, lowered so one result fits the window's budget. No limit goes above
    the SDK's own default."""
    budget = tool_budget(window)
    return ToolLimits(
        read_max_bytes=max(1, min(READ_MAX_BYTES, budget - READ_NOTE_BYTES)),
        glob_max_paths=max(1, min(GLOB_MAX_PATHS, budget // GLOB_PATH_BYTES)),
        grep_max_matches=max(1, min(GREP_MAX_MATCHES, budget // GREP_MATCH_BYTES)),
    )


def fit_output(output: str, budget: int) -> str:
    """``output`` cut to ``budget`` bytes, with a note saying it was cut to fit the context window
    and how to narrow the call, when it's over."""
    if utf8_size(output) <= budget:
        return output
    note = (
        f"\n[cut to {budget} bytes to fit the model's context window; narrow it with path or "
        "glob, or read with offset and limit]"
    )
    if utf8_size(note) > budget:
        return cut(output, budget)
    data = output.encode("utf-8")
    kept = data[: max(0, budget - utf8_size(note))].decode("utf-8", errors="ignore")
    return kept + note


def window_for(options: Options, model_length: int | None) -> int:
    """The run's context window: the options', else the default lowered to the model's length.
    Raises _RunEnded when the options ask for more than the model holds (design D7)."""
    if options.context_length is not None:
        if model_length is not None and options.context_length > model_length:
            raise _RunEnded(
                f"contextLength is {options.context_length}, but the model holds at most "
                f"{model_length} tokens. Give contextLength {model_length} or less.",
                "configuration",
            )
        return options.context_length
    if model_length is None:
        return DEFAULT_CONTEXT_LENGTH
    return min(DEFAULT_CONTEXT_LENGTH, model_length)


def room(window: int, count: int) -> int:
    """The most tokens an answer may take: the window less the conversation's count, less the
    margin for counting error (design D7). Zero or less means there's no room."""
    return window - count - TOKEN_MARGIN


class Conversation:
    """One run's conversation, from loading the model to its result."""

    def __init__(
        self,
        *,
        start: p.RunStartParams,
        options: Options,
        model: str,
        spec: LoadSpec,
        engine_version: str,
        loader: Loader,
        sink: Sink,
        load_timeout: float = LOAD_TIMEOUT_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._start = start
        self._options = options
        self._model = model
        self._spec = spec
        self._engine_version = engine_version
        self._loader = loader
        self._sink = sink
        self._load_timeout = load_timeout
        self._clock = clock
        self._started = clock()
        self._numbering = EventNumbering(
            start.run_id, start.limits.event_max_bytes, summary_max_bytes=SUMMARY_MAX_BYTES
        )
        # Made here, before run/start is answered, so a declaration the SDK can't use is refused;
        # the limits are lowered to the window once the model is loaded.
        self._declaration = Declaration.from_run_start(start)
        self._tools = Tools.for_declaration(self._declaration)
        self._engine: Engine | None = None
        self._window = 0
        self._budget = 0
        self._tool_definitions: list[dict[str, Any]] = []
        self._tools_tokens = 0
        self._messages: list[dict[str, Any]] = []
        self._counts: list[int] = []
        """Each message's tokens as the tokenizer counts it, with the template's overhead."""
        self._correction = 0
        """How many tokens the engine counted beyond the runner's count, at the last request."""
        self._results: list[_ToolResult] = []
        self._turn = 0
        self._requests = 0
        self._recorded = 0
        """How many messages the transcript holds already."""
        self._send_whole = True
        self._prompt_tokens: int | None = None
        self._output_tokens: int | None = None
        self._ended = False

    # Sending

    def _event(self, data: dict[str, Any], summary: str | None = None) -> None:
        if self._sink.stopping():
            raise _Stop
        data = {"runId": self._start.run_id, "seq": self._numbering.take(), **data}
        if summary is not None:
            data = fit(data, summary, SUMMARY_MAX_BYTES, self._start.limits.event_max_bytes)
        self._sink.event(p.parse_event(data))

    def _record(self, kind: p.TranscriptKind, value: object) -> None:
        if self._sink.stopping():
            raise _Stop
        self._sink.transcript(kind, encode(value))

    # The run

    def run(self) -> None:
        """Load the model and run the conversation to its result, or until the run stops."""
        try:
            self._run()
        except _Stop:
            return

    def _run(self) -> None:
        self._event(
            {
                "type": "init",
                "runner": {"name": NAME, "version": __version__},
                "engine": {
                    "name": ENGINE_NAME,
                    "version": self._engine_version,
                    "model": self._model,
                },
                "tools": Tools.names(),
                "effects": self._tools.mode,
            }
        )
        try:
            self._engine = self._load()
            self._window = window_for(self._options, self._engine.max_sequence_length())
            self._prepare()
            text = self._loop()
        except _RunEnded as end:
            self._result("error", end.message, end.reason)
            return
        self._result("ok", text or NO_TEXT)

    # Loading (design D4)

    def _load(self) -> Engine:
        """The loaded model, loaded on a thread of its own so the load's time is bounded: a load
        that fails, or passes the limit, ends the run with ``configuration``. A load can't be
        stopped, so one past the limit is left behind; the runner exits when troupe stops it."""
        self._event(
            {
                "type": "log",
                "level": "info",
                "message": f"Loading the model {self._model} in the runner's process.",
            },
            summary="message",
        )
        loaded: list[Engine] = []
        failed: list[EngineFailure] = []

        def load() -> None:
            try:
                loaded.append(self._loader(self._spec))
            except EngineFailure as error:
                failed.append(error)

        loading = threading.Thread(target=load, name="load", daemon=True)
        loading.start()
        loading.join(self._load_timeout)
        if self._sink.stopping():
            raise _Stop
        if loading.is_alive():
            raise _RunEnded(
                f"The model {self._model} didn't load within {self._load_timeout:g}s "
                "(LOAD_TIMEOUT_SECONDS).",
                "configuration",
            )
        if failed:
            raise _RunEnded(
                f"The engine couldn't load the model {self._model}: {failed[0].message}",
                "configuration",
            )
        return loaded[0]

    def _prepare(self) -> None:
        """Lower the tools' limits to the window, and count the tool definitions once."""
        self._budget = tool_budget(self._window)
        self._tools = Tools.for_declaration(self._declaration, tool_limits(self._window))
        self._tool_definitions = [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.input_schema,
                },
            }
            for tool in self._tools.offered()
        ]
        definitions = encode(self._tool_definitions).decode("utf-8")
        self._tools_tokens = self._count(definitions) + TOOLS_OVERHEAD_TOKENS
        if self._start.character is not None:
            self._add({"role": "system", "content": self._start.character})
        self._add({"role": "user", "content": self._start.direction})

    # The conversation

    def _loaded(self) -> Engine:
        if self._engine is None:  # pragma: no cover - the loop runs only after the load
            raise RuntimeError("the model isn't loaded")
        return self._engine

    def _count(self, text: str) -> int:
        try:
            return self._loaded().count(text)
        except EngineFailure as error:
            raise _RunEnded(
                f"The engine couldn't count tokens: {error.message}", "engine"
            ) from error

    def _message_tokens(self, message: Mapping[str, Any]) -> int:
        text = message.get("content") or ""
        calls = message.get("tool_calls")
        if calls:
            text += encode(calls).decode("utf-8")
        return self._count(text) + MESSAGE_OVERHEAD_TOKENS

    def _add(self, message: dict[str, Any]) -> None:
        self._messages.append(message)
        self._counts.append(self._message_tokens(message))

    def conversation_tokens(self) -> int:
        """The conversation's tokens, as the next request would send it (design D7)."""
        return self._tools_tokens + sum(self._counts) + self._correction

    def _request(self) -> ChatRequest:
        left = room(self._window, self.conversation_tokens())
        if left <= 0:
            raise _Full(
                f"The conversation is {self.conversation_tokens()} tokens, which leaves no room "
                f"in the run's context window of {self._window} tokens."
            )
        return ChatRequest(
            messages=list(self._messages),
            tools=self._tool_definitions,
            max_tokens=left,
            temperature=self._options.temperature,
            think=self._options.think,
        )

    def _send(self, request: ChatRequest) -> None:
        """Record what this request adds to the transcript: the whole of it the first time, and
        after a compaction; otherwise each message added since, then its settings."""
        if self._send_whole:
            self._record("sent", request.to_data())
            self._send_whole = False
        else:
            for message in self._messages[self._recorded :]:
                self._record("sent", message)
            self._record("sent", request.settings())
        self._recorded = len(self._messages)

    def _loop(self) -> str:
        while True:
            if self._requests >= self._options.max_turns:
                raise _RunEnded(
                    f"stopped after {self._requests} turns (maxTurns); the model was still "
                    "calling tools",
                    "turn-limit",
                )
            if self._compacting() and self.conversation_tokens() > self._window * COMPACT_AT_SHARE:
                self._compact(int(self._window * COMPACT_TO_SHARE))
            answer = self._answer()
            if not answer.tool_calls:
                return answer.content
            self._call_tools(answer)

    def _answer(self) -> Answer:
        """The answer to the next request. A run told to compact whose window fills compacts and
        asks again, as the same turn (compaction-opt-in design D6)."""
        while True:
            try:
                return self._ask()
            except _Full as full:
                if not self._compacting():
                    raise _RunEnded(
                        f"{full.message} The run's context window is {self._window} tokens: "
                        "raise contextLength, or give the actor a smaller task.",
                        "context-length",
                    ) from full
                if not self._compact(int(self._window * COMPACT_TO_SHARE)):
                    raise _RunEnded(
                        f"{full.message} onContextFull is compact, and compaction found nothing "
                        "more to remove: the tool results left are the latest turn's. Raise "
                        "contextLength, or give the actor a smaller task.",
                        "context-length",
                    ) from full

    def _ask(self) -> Answer:
        engine = self._loaded()
        request = self._request()
        self._send(request)
        self._requests += 1
        try:
            answer = engine.chat(request)
        except EngineFailure as error:
            if self._sink.stopping():
                raise _Stop from error
            if error.kind == "too-long":
                if self._compacting():
                    self._requests -= 1  # asked again after compacting, as the same turn
                raise _Full(f"The engine refused the request: {error.message}.") from error
            raise _RunEnded(f"The engine failed: {error.message}", "engine") from error
        self._record("received", dict(answer.record))
        self._counted(answer)
        if answer.finish_reason == "length":
            # The answer reached the room left: the window, the only limit the runner sets. Its
            # text is reported, its calls (which may be cut) aren't carried out (design D7).
            if self._compacting():
                self._requests -= 1
                raise _Full(
                    f"The model's answer filled the room left in the run's context window "
                    f"({request.max_tokens} tokens)."
                )
            self._turn_event(answer)
            raise _Full(
                f"The model's answer filled the room left in the run's context window "
                f"({request.max_tokens} tokens) and was cut there."
            )
        self._turn_event(answer)
        return answer

    def _counted(self, answer: Answer) -> None:
        """Count the answer into the run's usage, and correct the runner's count to the engine's."""
        if answer.prompt_tokens is not None:
            self._prompt_tokens = (self._prompt_tokens or 0) + answer.prompt_tokens
            estimated = self._tools_tokens + sum(self._counts)
            self._correction = max(0, answer.prompt_tokens - estimated)
        if answer.completion_tokens is not None:
            self._output_tokens = (self._output_tokens or 0) + answer.completion_tokens

    def _turn_event(self, answer: Answer) -> None:
        if answer.content:
            self._event({"type": "turn", "role": "assistant", "text": answer.content}, "text")

    # Compaction (compaction-opt-in design D4, D6; in-process-runner design D8)

    def _compacting(self) -> bool:
        return self._start.on_context_full == "compact"

    def _compact(self, target_tokens: int) -> bool:
        """Replace old tool results with the SDK's stub, oldest first, until the conversation is
        counted at ``target_tokens``, and say so with a context event. False when nothing could be
        removed."""
        tokens = self.conversation_tokens()
        size = sum(utf8_size(json.dumps(message)) for message in self._messages)
        target_bytes = int(size * target_tokens / tokens) if tokens else 0
        candidates = [
            Candidate(n, result.tool, result.size, result.turn == self._turn, result.stubbed)
            for n, result in enumerate(self._results)
        ]
        chosen = choose(candidates, size, target_bytes)
        if not chosen:
            return False
        removed = 0
        for n in chosen:
            result = self._results[n]
            text = stub(result.tool)
            self._messages[result.index] = {
                "role": "tool",
                "tool_call_id": result.call_id,
                "content": text,
            }
            self._counts[result.index] = self._message_tokens(self._messages[result.index])
            removed += result.size - utf8_size(text)
            result.stubbed = True
        if self._sink.stopping():
            raise _Stop
        count = len(self._messages)
        self._sink.event(
            context_event(
                self._numbering,
                "truncated",
                "runner",
                f"Removed {len(chosen)} old tool result{'' if len(chosen) == 1 else 's'} "
                f"({removed} bytes) to fit the {self._window}-token context window; the model "
                "can call each tool again.",
                messages_before=count,
                messages_after=count,
            )
        )
        self._send_whole = True
        return True

    # Tool calls

    def _call_tools(self, answer: Answer) -> None:
        calls = [
            (given.id or f"call-{self._requests}-{index}", given.name, given.arguments)
            for index, given in enumerate(answer.tool_calls)
        ]
        self._add(
            {
                "role": "assistant",
                "content": answer.content,
                "tool_calls": [
                    {"id": id_, "type": "function", "function": {"name": name, "arguments": args}}
                    for id_, name, args in calls
                ],
            }
        )
        self._turn += 1
        for call_id, name, arguments in calls:
            if self._sink.stopping():
                raise _Stop
            step = self._tools.run(call_id, name, arguments, self._numbering)
            if self._sink.stopping():
                raise _Stop
            for event in step.events:
                self._sink.event(event)
            content = fit_output(step.output, self._budget)
            self._results.append(
                _ToolResult(len(self._messages), name, call_id, utf8_size(content), self._turn)
            )
            self._add({"role": "tool", "tool_call_id": call_id, "content": content})

    # Ending

    def fail(self, message: str) -> None:
        """Report the runner's own failure, ``message``, as a log error and, if the run hasn't sent
        its result yet, an error result. Sends nothing once the run is stopping."""
        try:
            self._event({"type": "log", "level": "error", "message": message}, summary="message")
            if not self._ended:
                self._result("error", message, "runner")
        except _Stop:
            return

    def _usage(self) -> dict[str, int]:
        return {
            key: value
            for key, value in (
                ("inputTokens", self._prompt_tokens),
                ("outputTokens", self._output_tokens),
            )
            if value is not None
        }

    def _result(self, status: str, message: str, reason: p.FailureReason | None = None) -> None:
        usage = self._usage()
        data: dict[str, Any] = {
            "type": "result",
            "status": status,
            "message": message,
            "turns": self._requests,
            **({"reason": reason} if reason is not None else {}),
            "durationMs": max(0, int((self._clock() - self._started) * 1000)),
        }
        if usage:
            data["usage"] = usage
        self._event(data, summary="message")
        self._ended = True
