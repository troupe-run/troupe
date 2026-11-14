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
   the runner sent.
3. **The window the person named** (``contextWindow``). A reply whose prompt alone reaches it may
   already have been cut; one whose prompt and output reach it leaves no room for the next request.
"""

from dataclasses import dataclass
from typing import Final


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


def shrank(previous: int | None, current: int | None) -> bool:
    """Whether a reply's reported prompt is smaller than the previous request's: the engine
    answered from less of the conversation than it was sent (guard 2). False when either is
    unknown."""
    return previous is not None and current is not None and current < previous


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
    "SIGNALS",
    "Signal",
    "Window",
    "against_window",
    "shrank",
    "signal_of",
]
