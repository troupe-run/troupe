"""One run's conversation with Ollama: troupe's own tool loop (local-model-runner design D5 to D9,
D15).

The conversation builds each ``/api/chat`` request, reads each streamed answer, carries out the
model's tool calls with the plugin SDK's ``Tools``, and reports the run through a ``Sink``: run
events, transcript records, and whether the run is stopping. It holds the conversation itself, so
it records what it adds to it as well as what Ollama sends (D7), and it retries its own requests
(D9). It starts no thread and no process; the runner runs it on a worker thread and stops it
through the sink and the client.
"""

import contextlib
import json
import time
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from troupe_plugin_sdk import runner as p
from troupe_plugin_sdk.declaration import Declaration
from troupe_plugin_sdk.defaults import (
    BYTES_PER_TOKEN,
    GLOB_MAX_PATHS,
    GREP_MAX_MATCHES,
    READ_MAX_BYTES,
    ToolLimits,
)
from troupe_plugin_sdk.events import EventNumbering, ServedModels, cut, fit, utf8_size
from troupe_plugin_sdk.tools import Tools
from troupe_runner_ollama import NAME, __version__
from troupe_runner_ollama.client import Client, EngineError, RetryableError, StoppedError
from troupe_runner_ollama.defaults import (
    GLOB_PATH_BYTES,
    GREP_MATCH_BYTES,
    READ_NOTE_BYTES,
    RETRY_DELAY_SECONDS,
    RETRY_MAX_ATTEMPTS,
    SUMMARY_MAX_BYTES,
    TOOL_OUTPUT_SHARE,
)
from troupe_runner_ollama.options import Options

CONTEXT_REFUSAL = "exceeds the available context size"
"""The words in Ollama's message when it refuses a request longer than the context window (status
400, since every request asks it not to cut the conversation). Only a 400 holding them ends the
run with the reason ``context-length``; any other 400 is ``other`` (failure-reason design D6)."""

NO_TEXT = "(no text)"
"""The ok result's message when the model's last answer had no text."""


class Sink(Protocol):
    """Where the conversation sends what it reports, and how it learns the run is stopping."""

    def event(self, event: p.RunEvent) -> None: ...

    def transcript(self, kind: p.TranscriptKind, record: bytes) -> None:
        """One transcript record, verbatim, and its kind: ``sent`` for what the runner sent
        Ollama, ``received`` for what Ollama sent back. The sink sends it as base64 when it isn't
        UTF-8, and its kind only when troupe offered transcript-kinds."""
        ...

    def stopping(self) -> bool:
        """Whether the run is stopping: no further request, tool call or event."""
        ...

    def wait(self, seconds: float) -> bool:
        """Wait ``seconds``, or less if the run starts stopping. True when it is stopping."""
        ...


class _Stop(Exception):  # noqa: N818 - a signal to stop, not an error
    """The run is stopping: send nothing more."""


@dataclass
class _RunEnded(Exception):  # noqa: N818 - an ending, not an error of the runner's
    """The run ends with an error result holding ``message``, for ``reason``."""

    message: str
    reason: p.FailureReason


def engine_failure(error: EngineError) -> p.FailureReason:
    """The reason a status Ollama refused a request with ends the run for (failure-reason design
    D6): the context window only when Ollama's message says so, never from the status alone."""
    if error.status == 400 and CONTEXT_REFUSAL in error.message:
        return "context-length"
    if error.status in (401, 403):
        return "authentication"
    if error.status == 404:
        return "configuration"
    return "other"


def encode(value: object) -> bytes:
    """The bytes the runner sends for a JSON value: compact, UTF-8, the same everywhere, so a
    message recorded on its own is byte for byte what's inside the request (design D7)."""
    # A lone surrogate (which a \\ud800 escape in Ollama's JSON decodes to) can't be UTF-8: it's
    # written back as the same JSON escape, so encoding never fails.
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8", "backslashreplace"
    )


def tool_budget(window: int) -> int:
    """The UTF-8 bytes one tool result may take, for a context window of ``window`` tokens (design
    D15)."""
    return max(1, int(window * TOOL_OUTPUT_SHARE) * BYTES_PER_TOKEN)


def tool_limits(window: int) -> ToolLimits:
    """The SDK's tool limits, lowered so one result fits the window's budget (design D15). No limit
    goes above the SDK's own default."""
    budget = tool_budget(window)
    return ToolLimits(
        # Room for the SDK's own "read on with offset N" note, which it adds after the text it
        # read, so fit_output never has to cut it.
        read_max_bytes=max(1, min(READ_MAX_BYTES, budget - READ_NOTE_BYTES)),
        glob_max_paths=max(1, min(GLOB_MAX_PATHS, budget // GLOB_PATH_BYTES)),
        grep_max_matches=max(1, min(GREP_MAX_MATCHES, budget // GREP_MATCH_BYTES)),
    )


def fit_output(output: str, budget: int) -> str:
    """``output`` cut to ``budget`` bytes, with a note saying it was cut to fit the context window
    and how to narrow the call, when it's over (design D15)."""
    if utf8_size(output) <= budget:
        return output
    note = (
        f"\n[cut to {budget} bytes to fit the model's context window; narrow it with path or "
        "glob, or read with offset and limit]"
    )
    if utf8_size(note) > budget:  # a window too small for the note: just the output, cut
        return cut(output, budget)
    data = output.encode("utf-8")
    kept = data[: max(0, budget - utf8_size(note))].decode("utf-8", errors="ignore")
    return kept + note


@dataclass
class _Answer:
    content: str = ""
    thinking: str = ""
    tool_calls: list[Any] = field(default_factory=list)
    done_reason: str | None = None
    prompt_tokens: int | None = None
    cached_tokens: int | None = None
    output_tokens: int | None = None
    model: str | None = None
    """The model the answer's lines name: the first that names one."""


def _clean(value: Any) -> Any:  # noqa: ANN401 - JSON
    """``value`` with each lone surrogate in its strings replaced by ``?``. JSON can escape one
    (``\\ud800``), and json.loads decodes it, but it can't be UTF-8, so the SDK's summaries and
    tools would fail on it after an event's seq was taken. The transcript keeps the line as sent."""
    if isinstance(value, str):
        return value.encode("utf-8", "replace").decode("utf-8")
    if isinstance(value, list):
        return [_clean(item) for item in value]
    if isinstance(value, dict):
        return {_clean(key): _clean(item) for key, item in value.items()}
    return value


def _count(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


class Conversation:
    """One run's conversation, from its first request to its result."""

    def __init__(
        self,
        *,
        start: p.RunStartParams,
        options: Options,
        model: str,
        window: int,
        engine_version: str,
        client: Client,
        sink: Sink,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._start = start
        self._options = options
        self._model = model
        """The run's runtime's model (ollama-uses-runtime design D2)."""
        self._window = window
        self._engine_version = engine_version
        self._client = client
        self._sink = sink
        self._clock = clock
        self._started = clock()
        self._numbering = EventNumbering(
            start.run_id, start.limits.event_max_bytes, summary_max_bytes=SUMMARY_MAX_BYTES
        )
        self._budget = tool_budget(window)
        self._tools = Tools.for_declaration(Declaration.from_run_start(start), tool_limits(window))
        self._messages: list[bytes] = []
        self._requests = 0
        self._prompt_tokens: int | None = None
        self._cached_tokens = 0
        self._every_cached = True
        self._output_tokens: int | None = None
        self._ended = False
        self._served = ServedModels(model)

    # Building requests (design D5, D7)

    def _fields(self) -> dict[str, Any]:
        """Every field of a request but its messages: the same in every request."""
        options: dict[str, Any] = {"num_ctx": self._window}
        if self._options.temperature is not None:
            options["temperature"] = self._options.temperature
        if self._options.seed is not None:
            options["seed"] = self._options.seed
        fields: dict[str, Any] = {
            "model": self._model,
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.input_schema,
                    },
                }
                for tool in self._tools.offered()
            ],
            "stream": True,
            "truncate": False,
            "shift": False,
            "options": options,
        }
        if self._options.think is not None:
            fields["think"] = self._options.think
        return fields

    def _body(self) -> bytes:
        """The next request's exact bytes: its messages, each as encoded when it was added, then
        the other fields."""
        rest = encode(self._fields())
        return b'{"messages":[' + b",".join(self._messages) + b"]," + rest[1:]

    def _add(self, message: Mapping[str, Any], record: bool = True) -> None:
        encoded = encode(message)
        self._messages.append(encoded)
        if record:
            self._sink.transcript("sent", encoded)

    # Sending

    def _event(self, data: dict[str, Any], summary: str | None = None) -> None:
        if self._sink.stopping():
            raise _Stop
        data = {"runId": self._start.run_id, "seq": self._numbering.take(), **data}
        if summary is not None:
            data = fit(data, summary, SUMMARY_MAX_BYTES, self._start.limits.event_max_bytes)
        self._sink.event(p.parse_event(data))

    def _record(self, kind: p.TranscriptKind, line: bytes) -> None:
        if self._sink.stopping():
            raise _Stop
        self._sink.transcript(kind, line)

    # The run

    def run(self) -> None:
        """Run the conversation to its result, or until the run stops."""
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
                    "name": "ollama",
                    "version": self._engine_version,
                    "model": self._model,
                },
                "tools": Tools.names(),
                "effects": self._tools.mode,
            }
        )
        if self._start.character is not None:
            self._add({"role": "system", "content": self._start.character}, record=False)
        self._add({"role": "user", "content": self._start.direction}, record=False)
        try:
            text = self._loop()
        except _RunEnded as end:
            self._result("error", end.message, end.reason)
            return
        self._result("ok", text or NO_TEXT)

    def _loop(self) -> str:
        first = True
        while True:
            if self._requests >= self._options.max_turns:
                raise _RunEnded(
                    f"stopped after {self._requests} turns (maxTurns); the model was still "
                    "calling tools",
                    "turn-limit",
                )
            body = self._body()
            if first:
                self._record("sent", body)
                first = False
            answer = self._request(body)
            self._after(answer)
            if not answer.tool_calls:
                return answer.content
            self._call_tools(answer)

    def _request(self, body: bytes) -> _Answer:
        self._requests += 1
        for attempt in range(1, RETRY_MAX_ATTEMPTS + 1):
            if self._sink.stopping():
                raise _Stop
            try:
                return self._read(body)
            except StoppedError as error:
                raise _Stop from error
            except EngineError as error:
                self._record("received", error.body)
                message, reason = error.message, engine_failure(error)
                if reason == "context-length":
                    message += (
                        f". The run's context window is {self._window} tokens; raise "
                        "contextLength, or give the actor a smaller task."
                    )
                raise _RunEnded(message, reason) from error
            except RetryableError as error:
                if error.body is not None:
                    self._record("received", error.body)
                if attempt == RETRY_MAX_ATTEMPTS:
                    # The run ends with its last retry's reason (spec: runner-protocol).
                    raise _RunEnded(
                        f"gave up after {RETRY_MAX_ATTEMPTS} attempts: {error.message}",
                        error.reason,
                    ) from error
                delay = RETRY_DELAY_SECONDS * 2 ** (attempt - 1)
                self._event(
                    {
                        "type": "retry",
                        "attempt": attempt,
                        "maxAttempts": RETRY_MAX_ATTEMPTS,
                        "delayMs": int(delay * 1000),
                        "reason": error.reason,
                        "message": error.message,
                    },
                    summary="message",
                )
                if self._sink.wait(delay):
                    raise _Stop from error
        raise AssertionError("unreachable: the last attempt ends the run")  # pragma: no cover

    def _read(self, body: bytes) -> _Answer:
        """One attempt at a request: its answer, once Ollama's done line has come."""
        answer = _Answer()
        with contextlib.closing(self._client.chat(body)) as lines:
            return self._gather(answer, lines)

    def _gather(self, answer: _Answer, lines: Iterator[bytes]) -> _Answer:
        for line in lines:
            self._record("received", line)
            try:
                data = _clean(json.loads(line))
            except ValueError:
                data = None
            if not isinstance(data, dict):
                raise RetryableError("network", "Ollama sent a line that isn't a JSON object")
            if "error" in data:
                error = data["error"]
                text = error if isinstance(error, str) else json.dumps(data)
                raise _RunEnded(f"Ollama reported an error: {text}", "engine")
            if answer.model is None and isinstance(data.get("model"), str) and data["model"]:
                answer.model = data["model"]
            message = data.get("message")
            if isinstance(message, dict):
                if isinstance(message.get("content"), str):
                    answer.content += message["content"]
                if isinstance(message.get("thinking"), str):
                    answer.thinking += message["thinking"]
                if isinstance(message.get("tool_calls"), list):
                    answer.tool_calls.extend(message["tool_calls"])
            if data.get("done") is True:
                reason = data.get("done_reason")
                answer.done_reason = reason if isinstance(reason, str) else None
                answer.prompt_tokens = _count(data.get("prompt_eval_count"))
                answer.cached_tokens = _count(data.get("prompt_eval_cached_count"))
                answer.output_tokens = _count(data.get("eval_count"))
                return answer
        raise RetryableError("network", "the connection ended before Ollama finished its answer")

    def _after(self, answer: _Answer) -> None:
        """Report another model that answered, count the answer, report its text, and end the
        run if Ollama cut it."""
        for served in self._served.note(answer.model):
            self._event(served, "message" if served["type"] == "log" else None)
        # Ollama's prompt count includes the tokens it took from its cache. A cached count is
        # taken only beside the prompt it's part of, and cut to it (design D1, D2); whether every
        # answer had one decides the result's usage (D5).
        if answer.prompt_tokens is not None:
            self._prompt_tokens = (self._prompt_tokens or 0) + answer.prompt_tokens
        if answer.prompt_tokens is None or answer.cached_tokens is None:
            self._every_cached = False
        else:
            self._cached_tokens += min(answer.cached_tokens, answer.prompt_tokens)
        if answer.output_tokens is not None:
            self._output_tokens = (self._output_tokens or 0) + answer.output_tokens
        if answer.content:
            self._event({"type": "turn", "role": "assistant", "text": answer.content}, "text")
        if answer.done_reason == "length":
            # Cut output ends the run, unretried, and none of the answer's calls run (Decision
            # #279 point 4; ollama-output-limit design D1 to D3).
            raise _RunEnded(self._cut_message(answer), "output-limit")

    def _cut_message(self, answer: _Answer) -> str:
        """Why a cut answer ended the run (ollama-output-limit design D2)."""
        after = f" after {answer.output_tokens} tokens" if answer.output_tokens is not None else ""
        return (
            f"Ollama cut the model's answer at its output limit (done_reason length){after}. "
            "The runner sets no output limit, so Ollama stops an answer when the conversation "
            f"fills the run's context window of {self._window} tokens: raise contextLength, or "
            "give the actor a smaller task. A num_predict the model sets also cuts its answers."
        )

    def _call_tools(self, answer: _Answer) -> None:
        message: dict[str, Any] = {"role": "assistant", "content": answer.content}
        if answer.thinking:
            message["thinking"] = answer.thinking
        message["tool_calls"] = answer.tool_calls
        self._add(message)
        for index, call in enumerate(answer.tool_calls):
            if self._sink.stopping():
                raise _Stop
            function = call.get("function") if isinstance(call, dict) else None
            function = function if isinstance(function, dict) else {}
            given_id = call.get("id") if isinstance(call, dict) else None
            call_id = (
                given_id
                if isinstance(given_id, str) and given_id
                else f"call-{self._requests}-{index}"
            )
            name = function.get("name")
            name = name if isinstance(name, str) else ""
            arguments = function.get("arguments", {})
            if not isinstance(arguments, dict | str):
                arguments = encode(arguments).decode("utf-8")
            step = self._tools.run(call_id, name, arguments, self._numbering)
            if self._sink.stopping():
                raise _Stop
            for event in step.events:
                self._sink.event(event)
            self._add(
                {
                    "role": "tool",
                    "tool_name": name,
                    "content": fit_output(step.output, self._budget),
                }
            )

    def fail(self, message: str) -> None:
        """Report the runner's own failure, ``message``, as a log error and, if the run hasn't sent
        its result yet, an error result (design D3). Sends nothing once the run is stopping."""
        try:
            self._event({"type": "log", "level": "error", "message": message}, summary="message")
            if not self._ended:
                self._result("error", message, "runner")
        except _Stop:
            return

    def _usage(self) -> dict[str, int]:
        """The run's counters (design D5): the cache's reads apart from the input only when every
        answer reported them; otherwise the whole prompts are input and no cache read is
        reported."""
        input_tokens, cache_read_tokens = self._prompt_tokens, None
        if input_tokens is not None and self._every_cached:
            input_tokens -= self._cached_tokens
            cache_read_tokens = self._cached_tokens
        return {
            key: value
            for key, value in (
                ("inputTokens", input_tokens),
                ("outputTokens", self._output_tokens),
                ("cacheReadTokens", cache_read_tokens),
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
