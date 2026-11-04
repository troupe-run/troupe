"""The tool loop: from the direction to one result (spec: openai-chat-runner; openai-style-runner
design D6, D7, D9).

    messages = [system(instructions + character?), user(direction)]
    for turn in 1..maxTurns:
        reply = exchange(messages)               # retries inside
        turn event for its text, if any
        a refusal, content filter, length or unknown finish without calls: error result
        no tool calls: ok result with the text
        carry out each call in order through the SDK; add the assistant and tool messages
        the token budget spent: error result
    the turn limit reached: error result

The loop sends nothing itself: it hands each event and transcript record to the runner, which
masks and sends them. It returns the result event, or None when the run was stopped.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, TypeGuard

from troupe_plugin_sdk.events import EventNumbering, fit
from troupe_plugin_sdk.runner import (
    LogEvent,
    ResultEvent,
    RetryEvent,
    RunEvent,
    TurnEvent,
    Usage,
)
from troupe_plugin_sdk.tools import Tools
from troupe_runner_openai_chat.defaults import INSTRUCTIONS, SUMMARY_MAX_BYTES
from troupe_runner_openai_chat.exchange import (
    ExchangeFailedError,
    Record,
    Retry,
    Wait,
    exchange,
)
from troupe_runner_openai_chat.options import Options
from troupe_runner_openai_chat.runtime import Runtime
from troupe_runner_openai_chat.service import AbortedError, Call
from troupe_runner_openai_chat.stream import Reply

TOOL_FINISHES = ("tool_calls", "function_call", "stop")
"""Finish reasons a reply with tool calls may carry. Some compatible hosts finish a reply that asks
for tools with stop."""


def system_message(character: str | None) -> str:
    """The run's system message: the runner's fixed instructions, then the actor's character."""
    return INSTRUCTIONS if character is None else f"{INSTRUCTIONS}\n\n{character}"


def request_body(runtime: Runtime, messages: list[dict[str, Any]], tools: Tools) -> bytes:
    """One request's body: the runtime's model, the conversation, the SDK's tools, streamed with
    usage."""
    offered = [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.input_schema,
            },
        }
        for tool in tools.offered()
    ]
    body = {
        "model": runtime.model,
        "messages": messages,
        "tools": offered,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    return json.dumps(body, ensure_ascii=False).encode("utf-8")


@dataclass
class _Spend:
    """What the run's replies have used, and whether every one said."""

    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    cost_usd: float = 0.0
    usage_known: bool = True
    cost_known: bool = True
    requests: int = 0

    @property
    def tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def add(self, usage: dict[str, Any] | None) -> bool:
        """Add one reply's usage. False when it reported none, or a shape that can't be read."""
        self.requests += 1
        if usage is None:
            self.usage_known = self.cost_known = False
            return False
        prompt, completion = usage.get("prompt_tokens"), usage.get("completion_tokens")
        if not _count(prompt) or not _count(completion):
            self.usage_known = self.cost_known = False
            return False
        details = usage.get("prompt_tokens_details")
        found = details.get("cached_tokens") if isinstance(details, dict) else None
        cached = found if _count(found) else 0
        self.input_tokens += prompt
        self.output_tokens += completion
        self.cached_tokens += min(cached, prompt)
        cost = usage.get("cost")
        if isinstance(cost, int | float) and not isinstance(cost, bool) and cost >= 0:
            self.cost_usd += float(cost)
        else:
            self.cost_known = False
        return True

    def usage(self) -> Usage | None:
        if not self.usage_known or self.requests == 0:
            return None
        return Usage(
            input_tokens=self.input_tokens - self.cached_tokens,
            output_tokens=self.output_tokens,
            cache_read_tokens=self.cached_tokens,
        )

    def cost(self) -> float | None:
        return round(self.cost_usd, 10) if self.cost_known and self.requests else None


def _count(value: object) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


@dataclass
class Loop:
    """One run's tool loop. ``send`` takes each event, ``record`` each transcript record, ``wait``
    waits out a retry's delay (true when the run is stopping), and ``on_call`` is told of each
    request in flight so the runner can abort it."""

    runtime: Runtime
    options: Options
    tools: Tools
    numbering: EventNumbering
    send: Callable[[RunEvent], None]
    record: Record
    wait: Wait
    on_call: Callable[[Call | None], None] = lambda _: None
    stopping: Callable[[], bool] = lambda: False
    make_call: Callable[..., Call] = Call
    exchange_limits: dict[str, Any] = field(default_factory=dict)
    _ids: set[str] = field(default_factory=set)
    _made: int = 0
    _warned_usage: bool = False
    _noted_model: bool = False
    _spend: _Spend = field(default_factory=_Spend)

    def run(self, direction: str, character: str | None) -> ResultEvent | None:
        """Run the loop to its result. None when the run was stopped."""
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_message(character)},
            {"role": "user", "content": direction},
        ]
        spend = self._spend
        try:
            for turn in range(1, self.options.max_turns + 1):
                if self.stopping():
                    return None
                reply = self._exchange(messages)
                self._count(spend, reply)
                if reply.text:
                    self._send_turn(reply.text)
                ended = self._ended(reply, spend)
                if ended is not None:
                    return ended
                self._carry_out(reply, messages)
                if self.stopping():
                    return None
                if spend.usage_known and spend.tokens >= self.options.max_total_tokens:
                    return self._result(
                        "error",
                        f"The token budget of {self.options.max_total_tokens} was spent: the run "
                        f"used {spend.tokens} tokens over {turn} requests. Raise maxTotalTokens "
                        "in the actor's options to let it go further.",
                        spend,
                    )
            return self._result(
                "error",
                f"The turn limit of {self.options.max_turns} was reached while the model was still "
                "calling tools. Raise maxTurns in the actor's options to let it go further.",
                spend,
            )
        except ExchangeFailedError as error:
            return self._result("error", error.message, spend)
        except AbortedError:
            return None

    def failure(self, message: str) -> ResultEvent:
        """An error result for a failure of the runner's own, with what the run had used."""
        return self._result("error", message, self._spend)

    # One reply

    def _exchange(self, messages: list[dict[str, Any]]) -> Reply:
        return exchange(
            self.runtime.endpoint,
            request_body(self.runtime, messages, self.tools),
            self.runtime.credential,
            self._send_retry,
            self.record,
            self.wait,
            make_call=self.make_call,
            on_call=self.on_call,
            **self.exchange_limits,
        )

    def _count(self, spend: _Spend, reply: Reply) -> None:
        if not spend.add(reply.usage) and not self._warned_usage:
            self._warned_usage = True
            self._log(
                "warning",
                "The service reported no usage for a response, so the run's token budget can't "
                "be checked: only its turn limit bounds it, and its result has no usage.",
            )
        if reply.model and reply.model != self.runtime.model and not self._noted_model:
            self._noted_model = True
            self._log(
                "info",
                f"The service answered with the model {reply.model} (the runtime asked for "
                f"{self.runtime.model}).",
            )

    def _ended(self, reply: Reply, spend: _Spend) -> ResultEvent | None:
        """The result a reply ends the run with, or None when it asks for tools."""
        if reply.refusal is not None:
            return self._result("error", f"The model refused: {reply.refusal}", spend)
        if reply.finish == "content_filter":
            return self._result(
                "error", "The service's content filter stopped the response.", spend
            )
        if reply.finish == "length":
            return self._result(
                "error",
                "The response reached the service's output limit before the model finished.",
                spend,
            )
        if reply.tool_calls and reply.finish in TOOL_FINISHES:
            return None
        if reply.finish == "stop" and not reply.tool_calls:
            return self._result("ok", reply.text or "The model finished without a reply.", spend)
        if reply.tool_calls:
            return None
        return self._result(
            "error",
            f"The response finished with {reply.finish!r}, which the runner doesn't know, and "
            "asked for no tool.",
            spend,
        )

    def _carry_out(self, reply: Reply, messages: list[dict[str, Any]]) -> None:
        calls = []
        for call in reply.tool_calls:
            call_id = call.id if call.id and call.id not in self._ids else self._new_id()
            self._ids.add(call_id)
            calls.append((call_id, call))
        messages.append(
            {
                "role": "assistant",
                "content": reply.text or None,
                "tool_calls": [
                    {
                        "id": call_id,
                        "type": "function",
                        "function": {"name": call.name, "arguments": call.arguments},
                    }
                    for call_id, call in calls
                ],
            }
        )
        for call_id, call in calls:
            step = self.tools.run(call_id, call.name, call.arguments, self.numbering)
            for event in step.events:
                self.send(event)
            messages.append({"role": "tool", "tool_call_id": call_id, "content": step.output})

    def _new_id(self) -> str:
        while True:
            self._made += 1
            call_id = f"call-{self._made}"
            if call_id not in self._ids:
                return call_id

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

    def _result(self, status: str, message: str, spend: _Spend) -> ResultEvent:
        data: dict[str, Any] = {
            "runId": self.numbering.run_id,
            "seq": self.numbering.take(),
            "type": "result",
            "status": status,
            "message": message,
            "turns": spend.requests,
        }
        usage = spend.usage()
        if usage is not None:
            data["usage"] = usage.to_data()
        cost = spend.cost()
        if cost is not None:
            data["costUsd"] = cost
        return ResultEvent.from_data(self._fit(data, "message"))

    def _fit(self, data: dict[str, Any], key: str) -> dict[str, Any]:
        limit = min(self.numbering.summary_max_bytes, SUMMARY_MAX_BYTES)
        return fit(data, key, limit, self.numbering.event_max_bytes)


__all__ = ["TOOL_FINISHES", "Loop", "request_body", "system_message"]
