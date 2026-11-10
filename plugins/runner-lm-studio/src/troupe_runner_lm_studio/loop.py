"""One run, from the loaded model to its result (spec: lm-studio-runner; lmstudio-runner design D5,
D7, D8, D10, D11, D16).

    the pre-run check (before run/start is answered): LM Studio there, the model downloaded and
        trained for tool use
    then, after init:
    load the model (its context length reported when it isn't the run's)
    the library's tool loop, act(), over at most maxTurns rounds:
        answer text streamed: a turn at the round's first tool call, and at the round's end
        each tool call: carried out by the SDK, checked against the effects, reported as a pair
        a call the library rejected: answered with the SDK's own error for that input
        each round's end: its tokens counted; the budget spent with more rounds to come: stop
    a lost connection before any tool call has run: retried; after one has: an error result
    the result: ok, or an error with its reason

The library runs the rounds, so the run can't stop between them except by closing the client
(design D9). The run sends nothing itself: it hands each event and transcript record to the runner,
which numbers nothing twice and sends them under one lock.
"""

import json
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from troupe_plugin_sdk.cost import estimate
from troupe_plugin_sdk.events import EventNumbering, ServedModels, fit
from troupe_plugin_sdk.runner import (
    FailureReason,
    LogEvent,
    ResultEvent,
    RetryEvent,
    RunEvent,
    ServedModelEvent,
    TranscriptKind,
    TurnEvent,
    Usage,
)
from troupe_plugin_sdk.tools import Tools
from troupe_runner_lm_studio.defaults import (
    INSTRUCTIONS,
    MAX_ATTEMPTS,
    RETRY_BASE_DELAY_SECONDS,
    RETRY_MAX_DELAY_SECONDS,
    SUMMARY_MAX_BYTES,
)
from troupe_runner_lm_studio.engine import EngineError, Fragment, Model, Round, ToolSpec
from troupe_runner_lm_studio.options import Options
from troupe_runner_lm_studio.runtime import Runtime

STOP_REASONS: dict[str, tuple[FailureReason, str]] = {
    "contextLengthReached": (
        "context-length",
        "The model reached its context length of {context} tokens before it finished.",
    ),
    "maxPredictedTokensReached": (
        "output-limit",
        "The model reached LM Studio's limit on predicted tokens before it finished.",
    ),
    "modelUnloaded": ("engine", "LM Studio unloaded the model during the run."),
    "failed": ("engine", "LM Studio's prediction failed."),
}
"""A round's stop reason that ends the run with an error, its failure reason and what the result
says (design D16). eosFound and stopStringFound end it ok; any other is ``other``."""

FINISHED = ("eosFound", "stopStringFound")
"""The stop reasons of a model that finished its answer."""

FINAL_ROUND_ANSWER = (
    "This was the last round the run allows, so no more tool calls can be carried out. Reply "
    "with what you have done so far."
)
"""What the model is told when it asks for a tool on the last round, which is sent without
tools."""


class RefusedError(Exception):
    """The pre-run check refused the run: run/start's error, with its code, problem, fix and
    details."""

    def __init__(self, code: str, problem: str, fix: str, details: dict[str, str]) -> None:
        super().__init__(problem)
        self.code = code
        self.problem = problem
        self.fix = fix
        self.details = details


class EngineLike(Protocol):
    """What a run needs of its connection to LM Studio: engine.Engine, or a stand-in in tests."""

    def open(self) -> None: ...
    def models(self) -> list[Model]: ...
    def load(
        self, model: str, context_length: int, progress: Callable[[float], None]
    ) -> tuple[Any, int, str | None]: ...
    def act(
        self,
        handle: Any,  # noqa: ANN401 - the library's model handle
        history: dict[str, Any],
        definitions: Sequence[Any],
        *,
        max_rounds: int,
        temperature: float | None,
        fragment: Fragment,
        round_done: Callable[[Round], None],
        round_end: Callable[[int], None],
        message: Callable[[dict[str, Any]], None],
        invalid: Callable[[str, str | None, object], str],
    ) -> int: ...
    def close(self) -> None: ...
    def reopen(self) -> "EngineLike": ...


def check(engine: EngineLike, runtime: Runtime, tested: str) -> Model:
    """The pre-run check (design D6): LM Studio answers, its library lists the downloaded models,
    and the run's model is among them, an LLM trained for tool use. ``tested`` is the LM Studio
    version the runner's published requirements name."""
    endpoint = runtime.endpoint
    try:
        engine.open()
        models = engine.models()
    except EngineError as error:
        if error.failure == "incompatible":
            raise RefusedError(
                "lm-studio.incompatible",
                f"LM Studio answered at {endpoint}, but its library couldn't list the downloaded "
                f"models: {error.message}",
                f"Upgrade LM Studio: the runner was tested with LM Studio {tested}.",
                {"endpoint": endpoint},
            ) from None
        raise RefusedError(
            "lm-studio.unreachable",
            f"LM Studio didn't answer at {endpoint}: {error.message}",
            "Start LM Studio's server (lms server start), or set the runtime's endpoint to where "
            f"it listens. The runner was tested with LM Studio {tested}.",
            {"endpoint": endpoint},
        ) from None
    found = next((model for model in models if model.key == runtime.model), None)
    if found is None:
        raise RefusedError(
            "lm-studio.model-not-found",
            f"LM Studio at {endpoint} has no model downloaded with the key {runtime.model!r}.",
            f"Download it with lms get {runtime.model}, or give the actor a model LM Studio has "
            "(lms ls lists them).",
            {"model": runtime.model},
        )
    if found.type != "llm" or not found.trained_for_tool_use:
        what = "isn't a language model" if found.type != "llm" else "isn't trained for tool use"
        raise RefusedError(
            "lm-studio.model-without-tools",
            f"LM Studio's model {runtime.model!r} {what}, so it can't call the runner's tools.",
            "Give the actor a model LM Studio marks as trained for tool use.",
            {"model": runtime.model},
        )
    return found


def history(character: str | None, direction: str) -> dict[str, Any]:
    """The chat the run starts from: the runner's fixed instructions, then the actor's character,
    as the system prompt, and the direction as the one user message (design D7)."""
    system = INSTRUCTIONS if character is None else f"{INSTRUCTIONS}\n\n{character}"
    return {
        "messages": [
            {"role": "system", "content": [{"type": "text", "text": system}]},
            {"role": "user", "content": [{"type": "text", "text": direction}]},
        ]
    }


def tool_specs(tools: Tools) -> list[ToolSpec]:
    """The SDK's tools, as the run offers them."""
    return [ToolSpec(tool.name, tool.description, tool.input_schema) for tool in tools.offered()]


Record = Callable[[TranscriptKind, bytes], None]


def _json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=False).encode("utf-8")


@dataclass
class _State:
    """What the run has seen so far."""

    text: list[str] = field(default_factory=list)
    """Answer text streamed since the last turn was sent."""
    round_text: list[str] = field(default_factory=list)
    """All of this round's answer text, for the result's message."""
    last_text: str = ""
    turns: int = 0
    tool_calls: int = 0
    calls_this_round: int = 0
    rounds_with_calls: set[int] = field(default_factory=set)
    rounds: list[Round] = field(default_factory=list)
    prompt_tokens: int = 0
    predicted_tokens: int = 0
    usage_known: bool = True
    budget_spent: bool = False
    final_round_call: bool = False
    next_call: int = 0


@dataclass
class Run:
    """One run, once run/start is answered."""

    runtime: Runtime
    options: Options
    tools: Tools
    numbering: EventNumbering
    engine: EngineLike
    model: Model
    send: Callable[[RunEvent], None]
    record: Record
    wait: Callable[[float], bool]
    """Waits out a retry's delay; true when the run is stopping."""
    stopping: Callable[[], bool]
    make_definitions: Callable[[Sequence[ToolSpec], Callable[[str, dict[str, Any]], str]], Any]
    """engine.tool_definitions, or a stand-in in tests."""
    sent_tools: Callable[[Any], Any]
    """engine.sent_tools, or a stand-in in tests."""
    on_engine: Callable[[EngineLike], None] = lambda _: None
    """Told of each new engine a retry opens, so the runner can close it to stop."""
    _state: _State = field(default_factory=_State)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _served: ServedModels = field(default_factory=lambda: ServedModels(None))

    def run(self, character: str | None, direction: str) -> ResultEvent | None:
        """Run to the result. None when the run was stopped by troupe."""
        self._served = ServedModels(self.runtime.model)
        self.record("received", _json(self.model.info))
        chat = history(character, direction)
        definitions = self.make_definitions(tool_specs(self.tools), self._carry_out)
        self.record("sent", _json({"history": chat, "tools": self.sent_tools(definitions)}))
        attempt = 1
        while True:
            try:
                handle = self._load()
                rounds = self.engine.act(
                    handle,
                    chat,
                    definitions,
                    max_rounds=self.options.max_turns,
                    temperature=self.options.temperature,
                    fragment=self._fragment,
                    round_done=self._round_done,
                    round_end=self._round_end,
                    message=self._message,
                    invalid=self._invalid,
                )
                return self._finished(rounds)
            except EngineError as error:
                if self._state.budget_spent:
                    return self._budget()
                if self.stopping() or error.failure == "stopped":
                    return None
                if (
                    error.failure in ("lost", "unreachable")
                    and self._state.tool_calls == 0
                    and attempt < MAX_ATTEMPTS
                ):
                    delay = min(
                        RETRY_BASE_DELAY_SECONDS * 2 ** (attempt - 1), RETRY_MAX_DELAY_SECONDS
                    )
                    self._send_retry(attempt, delay, error.message)
                    if self.wait(delay):
                        return None
                    attempt += 1
                    self._state.text.clear()
                    self._state.round_text.clear()
                    self.engine = self.engine.reopen()
                    self.on_engine(self.engine)
                    try:
                        self.engine.open()
                    except EngineError as reopened:
                        error = reopened
                        if attempt < MAX_ATTEMPTS:
                            continue
                    else:
                        continue
                return self._from_error(error)

    def failure(self, message: str) -> ResultEvent:
        """An error result for a failure of the runner's own, with what the run had used."""
        return self._result("error", message, "runner")

    # Loading

    def _load(self) -> Any:  # noqa: ANN401 - the library's model handle
        wanted = self.options.context_length

        loading: list[float] = []

        def progress(fraction: float) -> None:
            # The library reports 1.0 for a model that was already loaded, too: only a load
            # that started is reported, at its start and its end.
            if fraction < 1 and not loading:
                self._log("info", f"LM Studio is loading {self.runtime.model}.")
            if loading or fraction < 1:
                loading.append(fraction)
            if fraction >= 1 and loading:
                self._log("info", f"LM Studio loaded {self.runtime.model}.")

        handle, context, served = self.engine.load(self.runtime.model, wanted, progress)
        self._note_model(served)
        if context != wanted:
            self._log(
                "info",
                f"{self.runtime.model} was already loaded with a context length of {context} "
                f"tokens, not the run's {wanted}, and the run uses it as it is.",
            )
        return handle

    # The library's callbacks

    def _fragment(self, text: str, reasoning: bool) -> None:
        if reasoning or not text:
            return
        with self._lock:
            self._state.text.append(text)
            self._state.round_text.append(text)

    def _flush_turn(self) -> None:
        """Send the answer text streamed since the last turn, as one turn."""
        with self._lock:
            text = "".join(self._state.text).strip()
            self._state.text.clear()
        if text:
            self._state.turns += 1
            self._send_turn(text)

    def _carry_out(self, name: str, arguments: dict[str, Any]) -> str:
        """One tool call the library asks for: carried out by the SDK, checked against the
        effects, and reported as a pair. None is carried out once the run is stopping."""
        if self.stopping() or self._state.budget_spent:
            return "The run was stopped, so the call wasn't carried out."
        return self._step(name, arguments)

    def _step(self, name: str, arguments: object) -> str:
        self._flush_turn()
        with self._lock:
            self._state.next_call += 1
            call_id = f"call-{self._state.next_call}"
            self._state.tool_calls += 1
            self._state.calls_this_round += 1
        raw = arguments if isinstance(arguments, dict | str) else {}
        step = self.tools.run(call_id, name, raw, self.numbering)
        for event in step.events:
            self.send(event)
        return step.output

    def _invalid(self, error: str, name: str | None, arguments: object) -> str:
        """A call the library rejected before carrying it out: answered with the SDK's own error
        for that input (design D7). With no name, a call on the last round, which is sent without
        tools: the run has reached its turn limit."""
        if name is None:
            self._state.final_round_call = True
            return FINAL_ROUND_ANSWER
        if self.stopping():
            return "The run was stopped, so the call wasn't carried out."
        return self._step(name, arguments)

    def _round_done(self, round_: Round) -> None:
        state = self._state
        state.rounds.append(round_)
        if round_.prompt_tokens is None or round_.predicted_tokens is None:
            state.usage_known = False
        else:
            state.prompt_tokens += round_.prompt_tokens
            state.predicted_tokens += round_.predicted_tokens
        self.record("received", _json(round_.record))
        self._note_model(round_.model_key)
        if state.calls_this_round:
            state.rounds_with_calls.add(round_.index)
        self._flush_turn()
        with self._lock:
            state.last_text = "".join(state.round_text).strip()
            state.round_text.clear()

    def _round_end(self, index: int) -> None:
        """After a round's tool calls have finished: the budget checked, and the run stopped when
        it's spent and the round asked for tools, so another would follow (design D5)."""
        state = self._state
        had_calls = index in state.rounds_with_calls
        state.calls_this_round = 0
        if had_calls and state.usage_known and self._tokens() >= self.options.max_total_tokens:
            state.budget_spent = True
            self.engine.close()

    def _message(self, message: dict[str, Any]) -> None:
        """The library's messages: a tool result message is what the run sends back (``sent``).
        The assistant's own is in its round's result, already recorded."""
        if message.get("role") == "tool":
            self.record("sent", _json(message))

    # Ending

    def _tokens(self) -> int:
        return self._state.prompt_tokens + self._state.predicted_tokens

    def _finished(self, rounds: int) -> ResultEvent | None:
        state = self._state
        if self.stopping():
            return None
        if state.budget_spent:
            return self._budget()
        limit = self.options.max_turns
        if state.final_round_call or (
            rounds >= limit and limit > 1 and (rounds - 2) in state.rounds_with_calls
        ):
            return self._result(
                "error",
                f"The turn limit of {limit} was reached while the model was still calling tools. "
                "Raise maxTurns in the actor's options to let it go further.",
                "turn-limit",
            )
        last = state.rounds[-1] if state.rounds else None
        stop = last.stop_reason if last is not None else "none"
        if stop in FINISHED:
            return self._result("ok", state.last_text or "The model finished without a reply.")
        known = STOP_REASONS.get(stop)
        if known is not None:
            reason, said = known
            return self._result("error", said.format(context=self.options.context_length), reason)
        return self._result(
            "error",
            f"LM Studio's prediction stopped for a reason the runner doesn't know: {stop}.",
            "other",
        )

    def _budget(self) -> ResultEvent:
        return self._result(
            "error",
            f"The token budget of {self.options.max_total_tokens} was spent: the run used "
            f"{self._tokens()} tokens over {len(self._state.rounds)} rounds. Raise maxTotalTokens "
            "in the actor's options to let it go further.",
            "budget",
        )

    def _from_error(self, error: EngineError) -> ResultEvent:
        if error.failure in ("lost", "unreachable", "timeout"):
            why = (
                " A retry could run a tool twice, so the run wasn't retried."
                if self._state.tool_calls
                else ""
            )
            return self._result(
                "error", f"The connection to LM Studio failed: {error.message}{why}", "network"
            )
        if error.failure == "unreadable":
            return self._result(
                "error",
                f"LM Studio sent something its library couldn't read: {error.message}",
                "other",
            )
        if error.failure == "model":
            return self._result(
                "error",
                f"LM Studio couldn't find the model {self.runtime.model}: {error.message}",
                "engine",
            )
        return self._result("error", f"LM Studio failed: {error.message}", "engine")

    # Events

    def _note_model(self, model: str | None) -> None:
        for body in self._served.note(model):
            if body["type"] == "served_model":
                data = {"runId": self.numbering.run_id, "seq": self.numbering.take(), **body}
                self.send(ServedModelEvent.from_data(data))
            else:
                self._log(body["level"], body["message"])

    def _send_turn(self, text: str) -> None:
        data = {
            "runId": self.numbering.run_id,
            "seq": self.numbering.take(),
            "type": "turn",
            "role": "assistant",
            "text": text,
        }
        self.send(TurnEvent.from_data(self._fit(data, "text")))

    def _send_retry(self, attempt: int, delay: float, message: str) -> None:
        data = {
            "runId": self.numbering.run_id,
            "seq": self.numbering.take(),
            "type": "retry",
            "attempt": attempt,
            "maxAttempts": MAX_ATTEMPTS,
            "delayMs": round(delay * 1000),
            "reason": "network",
            "message": f"The connection to LM Studio failed: {message}",
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

    def _usage(self) -> Usage | None:
        state = self._state
        if not state.usage_known or not state.rounds:
            return None
        return Usage(input_tokens=state.prompt_tokens, output_tokens=state.predicted_tokens)

    def _result(
        self, status: str, message: str, reason: FailureReason | None = None
    ) -> ResultEvent:
        data: dict[str, Any] = {
            "runId": self.numbering.run_id,
            "seq": self.numbering.take(),
            "type": "result",
            "status": status,
            "message": message,
            "turns": len(self._state.rounds),
        }
        if reason is not None:
            data["reason"] = reason
        usage = self._usage()
        if usage is not None:
            data["usage"] = usage.to_data()
        # LM Studio reports no cost: estimate one, but only from troupe's price (design D16).
        estimated = estimate(usage, self.runtime.price)
        if estimated is not None:
            data["estimatedCostUsd"] = estimated
        return ResultEvent.from_data(self._fit(data, "message"))

    def _fit(self, data: dict[str, Any], key: str) -> dict[str, Any]:
        limit = min(self.numbering.summary_max_bytes, SUMMARY_MAX_BYTES)
        return fit(data, key, limit, self.numbering.event_max_bytes)


__all__ = [
    "FINAL_ROUND_ANSWER",
    "FINISHED",
    "STOP_REASONS",
    "EngineLike",
    "RefusedError",
    "Run",
    "check",
    "history",
    "tool_specs",
]
