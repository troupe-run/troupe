"""The tool loop: from the direction to one result, over the Responses API (spec: openai-runner;
openai-style-runner design D6, D7, D9).

    instructions = runner instructions + character?
    input = [user(direction)]
    for turn in 1..maxTurns:
        reply = exchange(instructions, input)    # retries inside
        turn event for its text, if any
        a refusal, an incomplete or unknown status, a call without a call_id: error result
        no function call: ok result with the text
        carry out each call in order through the SDK
        input += the reply's output items, unchanged, then one function_call_output per call
        the token budget spent: error result
    the turn limit reached: error result

Every request is ``store: false`` and names no previous response, so the service keeps nothing of
the run and each request carries the whole conversation. The loop sends nothing itself: it hands
each event and transcript record to the runner, which masks and sends them. It returns the result
event, or None when the run was stopped.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, TypeGuard

from troupe_plugin_sdk.events import EventNumbering, fit
from troupe_plugin_sdk.runner import (
    FailureReason,
    LogEvent,
    ResultEvent,
    RetryEvent,
    RunEvent,
    TurnEvent,
    Usage,
)
from troupe_plugin_sdk.tools import Tools
from troupe_runner_openai.defaults import INSTRUCTIONS, SUMMARY_MAX_BYTES
from troupe_runner_openai.exchange import (
    ExchangeFailedError,
    Record,
    Retry,
    Wait,
    exchange,
)
from troupe_runner_openai.options import Options
from troupe_runner_openai.runtime import Runtime
from troupe_runner_openai.service import AbortedError, Call
from troupe_runner_openai.stream import Reply

INCOMPLETE: dict[str, tuple[str, FailureReason]] = {
    "max_output_tokens": (
        "The response reached the service's output limit before the model finished.",
        "output-limit",
    ),
    "content_filter": ("The service's content filter stopped the response.", "refused"),
}
"""What an incomplete response's reason means, in the result's words (design D8), and the
failure reason it ends the run with (failure-reason design D6). Any other is ``other``."""


def instructions(character: str | None) -> str:
    """The run's instructions: the runner's fixed instructions, then the actor's character."""
    return INSTRUCTIONS if character is None else f"{INSTRUCTIONS}\n\n{character}"


def request_body(
    runtime: Runtime, instructions_: str, input_: list[dict[str, Any]], tools: Tools
) -> bytes:
    """One request's body: the runtime's model, the instructions and the whole conversation, the
    SDK's tools (not strict, which the Responses API defaults to and the SDK's optional fields
    don't fit), streamed, and stored nowhere."""
    offered = [
        {
            "type": "function",
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.input_schema,
            "strict": False,
        }
        for tool in tools.offered()
    ]
    body = {
        "model": runtime.model,
        "instructions": instructions_,
        "input": input_,
        "tools": offered,
        "stream": True,
        "store": False,
        "include": ["reasoning.encrypted_content"],
    }
    return json.dumps(body, ensure_ascii=False).encode("utf-8")


@dataclass
class _Spend:
    """What the run's replies have used, and whether every one said."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_usd: float = 0.0
    usage_known: bool = True
    writes_known: bool = True
    cost_known: bool = True
    requests: int = 0

    @property
    def tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def add(self, usage: dict[str, Any] | None) -> bool:
        """Add one reply's usage. False when it reported none, or a shape that can't be read."""
        self.requests += 1
        if usage is None:
            self.usage_known = self.writes_known = self.cost_known = False
            return False
        given, made = usage.get("input_tokens"), usage.get("output_tokens")
        if not _count(given) or not _count(made):
            self.usage_known = self.writes_known = self.cost_known = False
            return False
        details = usage.get("input_tokens_details")
        details = details if isinstance(details, dict) else {}
        read, written = details.get("cached_tokens"), details.get("cache_write_tokens")
        read = read if _count(read) else 0
        if _count(written):
            self.cache_write_tokens += written
        else:
            self.writes_known = False
            written = 0
        self.input_tokens += given
        self.output_tokens += made
        self.cache_read_tokens += min(read, given)
        cost = usage.get("cost")
        if isinstance(cost, int | float) and not isinstance(cost, bool) and cost >= 0:
            self.cost_usd += float(cost)
        else:
            self.cost_known = False
        return True

    def usage(self) -> Usage | None:
        """The four counters (design D9): input less what was read from and written to the cache,
        the cache's reads and, when every response reported them, its writes."""
        if not self.usage_known or self.requests == 0:
            return None
        writes = self.cache_write_tokens if self.writes_known else 0
        return Usage(
            input_tokens=max(0, self.input_tokens - self.cache_read_tokens - writes),
            output_tokens=self.output_tokens,
            cache_read_tokens=self.cache_read_tokens,
            cache_write_tokens=self.cache_write_tokens if self.writes_known else None,
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
    _warned_usage: bool = False
    _noted_model: bool = False
    _spend: _Spend = field(default_factory=_Spend)

    def run(self, direction: str, character: str | None) -> ResultEvent | None:
        """Run the loop to its result. None when the run was stopped."""
        told = instructions(character)
        conversation: list[dict[str, Any]] = [{"role": "user", "content": direction}]
        spend = self._spend
        try:
            for turn in range(1, self.options.max_turns + 1):
                if self.stopping():
                    return None
                reply = self._exchange(told, conversation)
                self._count(spend, reply)
                if reply.text:
                    self._send_turn(reply.text)
                ended = self._ended(reply, spend)
                if ended is not None:
                    return ended
                conversation += self._carry_out(reply)
                if self.stopping():
                    return None
                if spend.usage_known and spend.tokens >= self.options.max_total_tokens:
                    return self._failed(
                        "budget",
                        f"The token budget of {self.options.max_total_tokens} was spent: the run "
                        f"used {spend.tokens} tokens over {turn} requests. Raise maxTotalTokens "
                        "in the actor's options to let it go further.",
                        spend,
                    )
            return self._failed(
                "turn-limit",
                f"The turn limit of {self.options.max_turns} was reached while the model was still "
                "calling tools. Raise maxTurns in the actor's options to let it go further.",
                spend,
            )
        except ExchangeFailedError as error:
            return self._failed(error.reason, error.message, spend)
        except AbortedError:
            return None

    def failure(self, message: str) -> ResultEvent:
        """An error result for a failure of the runner's own, with what the run had used."""
        return self._failed("runner", message, self._spend)

    # One reply

    def _exchange(self, told: str, conversation: list[dict[str, Any]]) -> Reply:
        return exchange(
            self.runtime.endpoint,
            request_body(self.runtime, told, conversation, self.tools),
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
            return self._failed("refused", f"The model refused: {reply.refusal}", spend)
        if reply.status == "incomplete":
            reason = reply.incomplete_reason
            said, failure = INCOMPLETE.get(reason or "") or (
                f"The response was left incomplete ({reason or 'no reason given'}).",
                "other",
            )
            return self._failed(failure, said, spend)
        if reply.status != "completed":
            return self._failed(
                "other",
                f"The response ended with the status {reply.status!r}, which the runner doesn't "
                "know.",
                spend,
            )
        missing = [call.name or "(no name)" for call in reply.tool_calls if not call.call_id]
        if missing:
            return self._failed(
                "engine",
                f"The service sent a tool call it can't be answered for, since it has no call_id: "
                f"{', '.join(missing)}.",
                spend,
            )
        if not reply.tool_calls:
            return self._result("ok", reply.text or "The model finished without a reply.", spend)
        return None

    def _carry_out(self, reply: Reply) -> list[dict[str, Any]]:
        """Carry out the reply's calls in order; what the next request adds to its input: the
        reply's output items unchanged, then each call's output."""
        outputs: list[dict[str, Any]] = []
        for call in reply.tool_calls:
            if self.stopping():
                break  # the run is stopping: carry out no more of its calls
            call_id = call.call_id or ""
            step = self.tools.run(call_id, call.name, call.arguments, self.numbering)
            for event in step.events:
                self.send(event)
            outputs.append(
                {"type": "function_call_output", "call_id": call_id, "output": step.output}
            )
        return [*reply.output, *outputs]

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

    def _failed(self, reason: FailureReason, message: str, spend: _Spend) -> ResultEvent:
        return self._result("error", message, spend, reason)

    def _result(
        self, status: str, message: str, spend: _Spend, reason: FailureReason | None = None
    ) -> ResultEvent:
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
        cost = spend.cost()
        if cost is not None:
            data["costUsd"] = cost
        return ResultEvent.from_data(self._fit(data, "message"))

    def _fit(self, data: dict[str, Any], key: str) -> dict[str, Any]:
        limit = min(self.numbering.summary_max_bytes, SUMMARY_MAX_BYTES)
        return fit(data, key, limit, self.numbering.event_max_bytes)


__all__ = ["INCOMPLETE", "Loop", "instructions", "request_body"]
