"""The tool loop: from the direction to one result, over the Messages API (spec: anthropic-runner;
anthropic-runner design D2, D5, D7, D8, D11).

    system = runner instructions + character?
    messages = [user(direction)]
    for turn in 1..maxTurns:
        reply = exchange(system, messages, tools)       # retries inside
        made from a cut conversation (context.py): not acted on; context-length, or compact
        served_model, then a turn event for its text, if any
        a stop reason that isn't tool_use: its result
        carry out each tool_use in order through the SDK
        messages += assistant(reply's content, unchanged), user(one tool_result per call)
        the token budget spent: error result
        the window the person named is full: context-length, or compact
    the turn limit reached: error result

The loop sends nothing itself: it hands each event and transcript record to the runner, which masks
and sends them. It returns the result event, or None when the run was stopped.
"""

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, TypeGuard

from troupe_plugin_sdk.compaction import Candidate, Estimate, choose, stub
from troupe_plugin_sdk.cost import estimate
from troupe_plugin_sdk.defaults import COMPACT_TO_SHARE
from troupe_plugin_sdk.events import EventNumbering, ServedModels, context_event, fit, utf8_size
from troupe_plugin_sdk.runner import (
    FailureReason,
    LogEvent,
    ResultEvent,
    RetryEvent,
    RunEvent,
    ServedModelEvent,
    TurnEvent,
    Usage,
)
from troupe_plugin_sdk.tools import Tools
from troupe_runner_anthropic.context import CONTEXT_STOP_REASON, against_window, shrank
from troupe_runner_anthropic.defaults import INSTRUCTIONS, SUMMARY_MAX_BYTES
from troupe_runner_anthropic.exchange import (
    ExchangeFailedError,
    Open,
    Record,
    Retry,
    StoppedError,
    Wait,
    exchange,
)
from troupe_runner_anthropic.options import Options
from troupe_runner_anthropic.reply import Reply
from troupe_runner_anthropic.runtime import Runtime

STOP_REASONS: dict[str, tuple[str, FailureReason]] = {
    "max_tokens": (
        "The reply reached the output limit the runner asked for (maxOutputTokens) before the "
        "model finished; nothing in it was carried out. Raise maxOutputTokens in the actor's "
        "options.",
        "output-limit",
    ),
    CONTEXT_STOP_REASON: (
        "The reply reached the model's context window before the model finished.",
        "context-length",
    ),
}
"""What a stop reason that ends the run means, in the result's words, and its reason. A refusal,
and any stop reason not here but ``tool_use``, ``end_turn`` and ``stop_sequence``, are handled in
``_ended`` (design D7)."""


def system_prompt(character: str | None) -> str:
    """The run's system prompt: the runner's fixed instructions, then the actor's character."""
    return INSTRUCTIONS if character is None else f"{INSTRUCTIONS}\n\n{character}"


def request_params(
    runtime: Runtime,
    options: Options,
    system: str,
    messages: list[dict[str, Any]],
    tools: Tools,
) -> dict[str, Any]:
    """One request's parameters: the runtime's model, the output limit, the system prompt, the whole
    conversation and the SDK's tools as custom tools, unchanged (design D2). No ``tool_choice``, so
    it's ``auto``; no ``thinking``, so it's the model's default."""
    return {
        "model": runtime.model,
        "max_tokens": options.max_output_tokens,
        "system": system,
        "messages": messages,
        "tools": [
            {"name": tool.name, "description": tool.description, "input_schema": tool.input_schema}
            for tool in tools.offered()
        ],
    }


@dataclass
class _Result:
    """A tool_result in the conversation, for compaction."""

    message: int
    """The user message's position in the conversation."""
    block: int
    """Its position in that message's content."""
    tool: str
    size: int
    turn: int
    stubbed: bool = False


def _count(value: object) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


@dataclass
class _Spend:
    """What the run's replies have used, as the Messages API counts it: input excludes both cache
    counters (design D7)."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    usage_known: bool = True
    reads_known: bool = True
    writes_known: bool = True
    requests: int = 0

    @property
    def tokens(self) -> int:
        return (
            self.input_tokens
            + self.output_tokens
            + self.cache_read_tokens
            + self.cache_write_tokens
        )

    def add(self, usage: Mapping[str, Any] | None) -> bool:
        """Add one reply's usage. False when it reported none, or a shape that can't be read."""
        self.requests += 1
        given = None if usage is None else usage.get("input_tokens")
        made = None if usage is None else usage.get("output_tokens")
        if usage is None or not _count(given) or not _count(made):
            self.usage_known = self.reads_known = self.writes_known = False
            return False
        read, written = (
            usage.get("cache_read_input_tokens"),
            usage.get("cache_creation_input_tokens"),
        )
        if _count(read):
            self.cache_read_tokens += read
        else:
            self.reads_known = False
        if _count(written):
            self.cache_write_tokens += written
        else:
            self.writes_known = False
        self.input_tokens += given
        self.output_tokens += made
        return True

    def usage(self) -> Usage | None:
        if not self.usage_known or self.requests == 0:
            return None
        return Usage(
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            cache_read_tokens=self.cache_read_tokens if self.reads_known else None,
            cache_write_tokens=self.cache_write_tokens if self.writes_known else None,
        )


class _Cut(Exception):  # noqa: N818 - control flow, not an error
    """A reply made from less than the conversation, or a window that's full: ends a run told to
    fail, and compacts one told to compact."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass
class Loop:
    """One run's tool loop. ``open`` sends one request through the service seam, ``send`` takes
    each event, ``record`` each transcript record, ``wait`` waits out a retry's delay (true when the
    run is stopping), and ``begin`` and ``end`` bracket each request in flight, ``begin`` returning
    False when the run is stopping."""

    runtime: Runtime
    options: Options
    tools: Tools
    numbering: EventNumbering
    open: Open
    send: Callable[[RunEvent], None]
    record: Record
    wait: Wait
    begin: Callable[[], bool] = lambda: True
    end: Callable[[], None] = lambda: None
    stopping: Callable[[], bool] = lambda: False
    exchange_limits: dict[str, Any] = field(default_factory=dict)
    compact: bool = False
    """Whether run/start's onContextFull is compact."""
    _warned_usage: bool = False
    _results: list[_Result] = field(default_factory=list)
    _turn: int = 0
    _estimate: Estimate = field(default_factory=Estimate)
    _previous_prompt: int | None = None
    """The reported prompt of the last reply acted on, or None after a compaction, which shrinks the
    conversation on purpose (design D8, guard 2)."""
    _accepted_prompt: int | None = None
    _served: ServedModels | None = None
    _spend: _Spend = field(default_factory=_Spend)

    def run(self, direction: str, character: str | None) -> ResultEvent | None:
        """Run the loop to its result. None when the run was stopped."""
        system = system_prompt(character)
        messages: list[dict[str, Any]] = [{"role": "user", "content": direction}]
        spend = self._spend
        try:
            for turn in range(1, self.options.max_turns + 1):
                if self.stopping():
                    return None
                reply = self._reply(system, messages)
                self._note_model(reply)
                if reply.text:
                    self._send_turn(reply.text)
                ended = self._ended(reply)
                if ended is not None:
                    return ended
                messages += self._carry_out(reply, len(messages))
                if self.stopping():
                    return None
                if spend.usage_known and spend.tokens >= self.options.max_total_tokens:
                    return self._failed(
                        "budget",
                        f"The token budget of {self.options.max_total_tokens} was spent: the run "
                        f"used {spend.tokens} tokens over {turn} requests. Raise maxTotalTokens "
                        "in the actor's options to let it go further.",
                    )
                window = against_window(
                    self.options.context_window,
                    reply.prompt_tokens,
                    (reply.usage or {}).get("output_tokens"),
                )
                if window.full:
                    said = (
                        f"The conversation has reached the context window of "
                        f"{self.options.context_window} tokens the actor's options name "
                        "(contextWindow), so the next request wouldn't fit."
                    )
                    if not self.compact:
                        return self._failed("context-length", said)
                    if not self._compact(messages, said):
                        return self._failed("context-length", self._nothing_left(said))
            return self._failed(
                "turn-limit",
                f"The turn limit of {self.options.max_turns} was reached while the model was still "
                "calling tools. Raise maxTurns in the actor's options to let it go further.",
            )
        except ExchangeFailedError as error:
            if error.usage is not None:
                spend.add(error.usage)
            return self._failed(error.reason, error.message)
        except _Cut as cut:
            return self._failed("context-length", cut.message)
        except StoppedError:
            return None

    def failure(self, message: str) -> ResultEvent:
        """An error result for a failure of the runner's own, with what the run had used."""
        return self._failed("runner", message)

    # One reply

    def _reply(self, system: str, messages: list[dict[str, Any]]) -> Reply:
        """The reply to the next request, made from the whole conversation (design D8). In a run
        told to compact, a context refusal, or a reply made from a cut conversation, compacts the
        conversation and asks again, as the same turn; with nothing left to remove, the run ends
        with context-length."""
        while True:
            params = request_params(self.runtime, self.options, system, messages, self.tools)
            size = len(json.dumps(params, ensure_ascii=False).encode("utf-8"))
            try:
                reply = self._exchange(params)
            except ExchangeFailedError as error:
                if not (self.compact and error.context):
                    raise
                if not self._compact(messages, error.message, size):
                    raise ExchangeFailedError(
                        self._nothing_left(error.message), "context-length"
                    ) from error
                continue
            self._count(reply)
            cut = self._cut(reply)
            if cut is None:
                prompt = reply.prompt_tokens
                if prompt is not None and prompt > 0:
                    self._estimate.calibrate(size, prompt)
                    self._accepted_prompt = prompt
                    self._previous_prompt = prompt
                return reply
            if not self.compact:
                raise _Cut(cut)
            if not self._compact(messages, cut, size):
                raise _Cut(self._nothing_left(cut))

    def _cut(self, reply: Reply) -> str | None:
        """Why ``reply`` was made from less than the conversation, or None (guards 2 and 3)."""
        prompt = reply.prompt_tokens
        if shrank(self._previous_prompt, prompt):
            return (
                f"The engine answered from less of the conversation than it was sent: it reported "
                f"a prompt of {prompt} tokens, after {self._previous_prompt} for the request "
                "before, though the conversation only grows. It cut the conversation to fit its "
                "context, so the reply wasn't acted on. Give the actor a smaller task, or a model "
                "with a longer context."
            )
        window = self.options.context_window
        if against_window(window, prompt, None).cut:
            return (
                f"The request's prompt was {prompt} tokens, reaching the context window of "
                f"{window} tokens the actor's options name (contextWindow), so the engine may have "
                "cut it; the reply wasn't acted on."
            )
        return None

    @staticmethod
    def _nothing_left(said: str) -> str:
        return (
            f"{said} onContextFull is compact, and compaction found nothing more to remove: the "
            "tool results left are the latest turn's."
        )

    def _compact(self, messages: list[dict[str, Any]], why: str, size: int | None = None) -> bool:
        """Replace the oldest tool results with the SDK's stub, down to a share of the last whole
        request, and say so with a context event. False when nothing could be removed."""
        if size is None:
            size = len(json.dumps(messages, ensure_ascii=False).encode("utf-8"))
        target = int(size * COMPACT_TO_SHARE)
        if self._accepted_prompt is not None:
            target = min(
                target, self._estimate.bytes(int(self._accepted_prompt * COMPACT_TO_SHARE))
            )
        candidates = [
            Candidate(n, result.tool, result.size, result.turn == self._turn, result.stubbed)
            for n, result in enumerate(self._results)
        ]
        chosen = choose(candidates, size, target)
        if not chosen:
            return False
        removed = 0
        for n in chosen:
            result = self._results[n]
            text = stub(result.tool)
            content = list(messages[result.message]["content"])
            content[result.block] = {**content[result.block], "content": text}
            messages[result.message] = {**messages[result.message], "content": content}
            removed += result.size - utf8_size(text)
            result.stubbed = True
        # The conversation shrank on purpose: the next reply's prompt isn't compared with the last.
        self._previous_prompt = None
        self.send(
            context_event(
                self.numbering,
                "truncated",
                "runner",
                f"Removed {len(chosen)} old tool result{'' if len(chosen) == 1 else 's'} "
                f"({removed} bytes) to make room in the context: {why} The model can call each "
                "tool again.",
                messages_before=len(messages),
                messages_after=len(messages),
            )
        )
        return True

    def _exchange(self, params: dict[str, Any]) -> Reply:
        return exchange(
            self.open,
            params,
            self.runtime.endpoint.messages_url,
            self._send_retry,
            self.record,
            self.wait,
            begin=self.begin,
            end=self.end,
            **self.exchange_limits,
        )

    def _count(self, reply: Reply) -> None:
        if not self._spend.add(reply.usage) and not self._warned_usage:
            self._warned_usage = True
            self._log(
                "warning",
                "The service reported no usage for a reply, so the run's token budget and its "
                "context can't be checked: only its turn limit bounds it, and its result has no "
                "usage.",
            )

    def _note_model(self, reply: Reply) -> None:
        if self._served is None:
            self._served = ServedModels(self.runtime.model)
        for body in self._served.note(reply.model):
            if body["type"] == "served_model":
                data = {"runId": self.numbering.run_id, "seq": self.numbering.take(), **body}
                self.send(ServedModelEvent.from_data(data))
            else:
                self._log(body["level"], body["message"])

    def _ended(self, reply: Reply) -> ResultEvent | None:
        """The result a reply ends the run with, or None when it asks for tools."""
        reason = reply.stop_reason
        if reason == "tool_use":
            if not reply.tool_uses:
                return self._failed(
                    "engine", "The reply stopped to use a tool, but asked for none."
                )
            return None
        if reason in ("end_turn", "stop_sequence"):
            return self._result("ok", reply.text or "The model finished without a reply.")
        if reason == "refusal":
            details = (
                f" ({json.dumps(reply.stop_details, ensure_ascii=False)})"
                if reply.stop_details is not None
                else ""
            )
            said = f": {reply.text}" if reply.text else ""
            return self._failed("refused", f"The model refused{details}{said}")
        if reason in STOP_REASONS:
            said, failure = STOP_REASONS[reason]
            return self._failed(failure, said)
        return self._failed(
            "engine",
            f"The reply stopped for a reason the runner doesn't act on: {reason!r}.",
        )

    def _carry_out(self, reply: Reply, at: int) -> list[dict[str, Any]]:
        """Carry out the reply's calls in order; what the next request adds, from position ``at``:
        the reply's content unchanged, then one user message holding each call's result."""
        self._turn += 1
        results: list[dict[str, Any]] = []
        for use in reply.tool_uses:
            if self.stopping():
                break  # the run is stopping: carry out no more of its calls
            step = self.tools.run(use.call_id, use.name, use.arguments, self.numbering)
            for event in step.events:
                self.send(event)
            self._results.append(
                _Result(at + 1, len(results), use.name, utf8_size(step.output), self._turn)
            )
            result: dict[str, Any] = {
                "type": "tool_result",
                "tool_use_id": use.call_id,
                "content": step.output,
            }
            if step.is_error:
                result["is_error"] = True
            results.append(result)
        return [
            {"role": "assistant", "content": reply.content},
            {"role": "user", "content": results},
        ]

    # Events

    def _send_turn(self, text: str) -> None:
        data = {
            "runId": self.numbering.run_id,
            "seq": self.numbering.take(),
            "type": "turn",
            "role": "assistant",
            "text": text,
        }
        self.send(TurnEvent.from_data(self._fit(data, "text")))

    def _send_retry(self, retry: Retry) -> None:
        data = {
            "runId": self.numbering.run_id,
            "seq": self.numbering.take(),
            "type": "retry",
            "attempt": retry.attempt,
            "maxAttempts": retry.max_attempts,
            "delayMs": round(retry.delay_seconds * 1000),
            "reason": retry.reason,
            "message": retry.message,
        }
        self.send(RetryEvent.from_data(self._fit(data, "message")))

    def _log(self, level: str, message: str) -> None:
        data = {
            "runId": self.numbering.run_id,
            "seq": self.numbering.take(),
            "type": "log",
            "level": level,
            "message": message,
        }
        self.send(LogEvent.from_data(self._fit(data, "message")))

    def _failed(self, reason: FailureReason, message: str) -> ResultEvent:
        return self._result("error", message, reason)

    def _result(
        self, status: str, message: str, reason: FailureReason | None = None
    ) -> ResultEvent:
        spend = self._spend
        data: dict[str, Any] = {
            "runId": self.numbering.run_id,
            "seq": self.numbering.take(),
            "type": "result",
            "status": status,
            "message": message,
            "turns": spend.requests,
        }
        if reason is not None:
            data["reason"] = reason
        usage = spend.usage()
        if usage is not None:
            data["usage"] = usage.to_data()
        # The Messages API reports no cost: estimate one, only from troupe's price.
        estimated = estimate(usage, self.runtime.price)
        if estimated is not None:
            data["estimatedCostUsd"] = estimated
        return ResultEvent.from_data(self._fit(data, "message"))

    def _fit(self, data: dict[str, Any], key: str) -> dict[str, Any]:
        limit = min(self.numbering.summary_max_bytes, SUMMARY_MAX_BYTES)
        return fit(data, key, limit, self.numbering.event_max_bytes)


__all__ = ["STOP_REASONS", "Loop", "request_params", "system_prompt"]
