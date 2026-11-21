"""The context guard: never act on a reply made from a cut conversation (anthropic-runner design
D8).

Engines that serve the Messages API don't all refuse a conversation longer than their context. The
probe (troupe#415) found LM Studio and Ollama both cut it and answer 200, with nothing in the API to
stop them. So the runner judges three things, all here:

1. **Signals.** A failure one of the engines says is about its context, from one table. Each entry
   names its engine and the fixture that pins it. A signal the table doesn't know falls to the
   general rules, which end the run loudly, never silently.
2. **A shrinking prompt.** Every request is the previous one plus the reply and the results, so a
   reply reported as answering a smaller prompt than the request before it was made from less than
   the runner sent. How big a prompt was depends on how the engine counts cached input, which
   ``ENGINES`` says (local-engine-context design D2, D3).
3. **The window the person named** (``contextWindow``). A reply whose prompt alone reaches it may
   already have been cut; one whose prompt and output reach it leaves no room for the next request.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final


@dataclass(frozen=True)
class Signal:
    """One engine's way of saying a request is longer than its context."""

    engine: str
    status: int | None
    """The status, or None for any: a streamed request's refusal comes as an ``error`` event in a
    200 stream, a request that isn't streamed as the status."""
    error_type: str | None
    """The error's ``type``, or None for any."""
    says: str
    """Text the error's message holds, compared case-insensitively."""
    pinned_by: str
    """The fixture, or the documentation, it's taken from."""


SIGNALS: Final[tuple[Signal, ...]] = (
    Signal(
        "Claude's API",
        400,
        "invalid_request_error",
        "prompt is too long",
        "fixtures/claude-context-refused, recorded by the owner from claude-haiku-5-5",
    ),
    Signal(
        "LM Studio",
        None,
        "api_error",
        "greater than the context length",
        "fixtures/lm-studio-context-refused (an error event in a stream; not streamed, a 500)",
    ),
    Signal(
        "llama.cpp",
        400,
        "exceed_context_size_error",
        "context",
        "llama.cpp server documentation (exceed_context_size_error); not yet probed",
    ),
)
"""Each engine's context refusal the runner knows, in one place."""


@dataclass(frozen=True)
class Engine:
    """How one engine counts a reply's input (local-engine-context design D2)."""

    value: str
    """The runtime's ``engine``, as the protocol names it."""
    name: str
    """The engine's name in words, as ``Signal.engine`` gives it."""
    reads_in_input: bool | None
    """Whether its ``input_tokens`` already holds its cache reads: True, False, or None when it
    isn't known, and the runner then counts and guards as for a runtime that names no engine."""
    pinned_by: str
    """The fixture, probe or documentation it's taken from."""


ENGINES: Final[dict[str, Engine]] = {
    engine.value: engine
    for engine in (
        Engine(
            "claude",
            "Claude's API",
            False,
            "the Messages API's documentation: input_tokens excludes cache reads and writes",
        ),
        Engine(
            "lm-studio",
            "LM Studio",
            True,
            "fixtures/lm-studio-tool-loop (126 input tokens with 89 cache reads for a prompt of "
            "about 126), and the troupe#415 probe; troupe#419",
        ),
        Engine(
            "ollama",
            "Ollama",
            False,
            "the troupe#415 probe of Ollama 0.40.14 (30 input tokens with 374 cache reads)",
        ),
        Engine("llama.cpp", "llama.cpp", None, "not yet probed"),
    )
}
"""Each engine a runtime may name, by its value: one entry for each in the protocol's set
(troupe_plugin_sdk.runner.RUNTIME_ENGINES), which a test checks."""


def reads_in_input(engine: str | None) -> bool | None:
    """Whether ``engine``'s input_tokens holds its cache reads; None for no engine, or one whose
    accounting isn't known."""
    return None if engine is None else ENGINES[engine].reads_in_input


def _count(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return None


def prompt_readings(usage: Mapping[str, Any] | None, reads: bool | None) -> tuple[int, ...] | None:
    """A reply's prompt, as big as its usage says, by each reading the engine's accounting allows
    (design D3): one when it's known, two when it isn't (cache reads inside input_tokens, then
    apart). None when input_tokens isn't a count."""
    given = _count((usage or {}).get("input_tokens"))
    if given is None:
        return None
    read = _count((usage or {}).get("cache_read_input_tokens")) or 0
    written = _count((usage or {}).get("cache_creation_input_tokens")) or 0
    inside, apart = given + written, given + read + written
    if reads is None:
        return (inside, apart)
    return (inside,) if reads else (apart,)


def largest(readings: tuple[int, ...] | None) -> int | None:
    """The largest reading: what the window and the compaction estimate judge by (design D3)."""
    return None if readings is None else max(readings)


CONTEXT_STOP_REASON: Final = "model_context_window_exceeded"
"""The stop reason Claude's API gives when a reply reached the model's context window."""


def signal_of(status: int, error_type: str | None, message: str | None) -> Signal | None:
    """The table's entry a failure matches, or None."""
    said = (message or "").lower()
    for signal in SIGNALS:
        if signal.status is not None and status != signal.status:
            continue
        if signal.error_type is not None and error_type != signal.error_type:
            continue
        if signal.says.lower() in said:
            return signal
    return None


def shrank(previous: tuple[int, ...] | None, current: tuple[int, ...] | None) -> bool:
    """Whether a reply's reported prompt is smaller than the previous request's by any reading the
    two share: the engine answered from less of the conversation than it was sent (guard 2; design
    D3). False when either is unknown."""
    if previous is None or current is None:
        return False
    return any(now < before for before, now in zip(previous, current, strict=True))


@dataclass(frozen=True)
class Window:
    """What a reply's sizes mean against the window the person named (guard 3)."""

    cut: bool
    """Its prompt alone reached the window, so the engine may have cut it: not acted on."""
    full: bool
    """Its prompt and output reached the window: acted on, but no further request fits."""


def against_window(window: int | None, prompt: int | None, output: int | None) -> Window:
    """A reply's prompt and output tokens against ``window``; neither cut nor full when there's
    no window or no prompt size."""
    if window is None or prompt is None:
        return Window(cut=False, full=False)
    return Window(cut=prompt >= window, full=prompt + (output or 0) >= window)


__all__ = [
    "CONTEXT_STOP_REASON",
    "ENGINES",
    "SIGNALS",
    "Engine",
    "Signal",
    "Window",
    "against_window",
    "largest",
    "prompt_readings",
    "reads_in_input",
    "shrank",
    "signal_of",
]
