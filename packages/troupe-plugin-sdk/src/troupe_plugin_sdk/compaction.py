"""What a runner that holds its own conversation needs to compact it (compaction-opt-in design D4,
D6, D7): which old tool results to replace, the text that replaces them, and an estimate of the
conversation's tokens from its bytes.

The SDK has no conversation type: each runner offers its tool results as ``Candidate``s in
conversation order, replaces the content of the ones ``choose`` returns with ``stub(tool)``, and
reports the compaction with ``troupe_plugin_sdk.events.context_event``. Nothing here calls a
model, so a compaction costs no tokens.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass

from troupe_plugin_sdk.defaults import BYTES_PER_TOKEN
from troupe_plugin_sdk.events import utf8_size


@dataclass(frozen=True)
class Candidate:
    """One tool result in the runner's conversation. ``index`` is the runner's own position for
    it, given back by ``choose``. ``latest`` marks a result of the latest turn, which the model
    hasn't read yet, and ``stubbed`` one already replaced: ``choose`` never picks either."""

    index: int
    tool: str
    size: int
    """The result's content, in UTF-8 bytes."""
    latest: bool = False
    stubbed: bool = False


def stub(tool: str) -> str:
    """The text that replaces a removed result of ``tool``: one wording for every runner, saying
    what was removed and how to get it back."""
    return (
        f"[troupe removed this {tool} result to make room in the context window. "
        f"Call {tool} again if you still need it.]"
    )


def saving(candidate: Candidate) -> int:
    """The bytes replacing ``candidate`` with its stub saves: zero or less when the result is no
    larger than its stub."""
    return candidate.size - utf8_size(stub(candidate.tool))


def choose(candidates: Sequence[Candidate], estimate_bytes: int, target_bytes: int) -> list[int]:
    """The indexes of the results to stub, oldest first, to bring ``estimate_bytes`` down to
    ``target_bytes``. Skips a result of the latest turn, one already stubbed and one no larger
    than its stub, and stops once the estimate is at or below the target. When the target can't
    be reached, it still chooses every result that saves something; an empty list means nothing
    can help."""
    chosen: list[int] = []
    remaining = estimate_bytes
    for candidate in candidates:
        if remaining <= target_bytes:
            break
        if candidate.latest or candidate.stubbed:
            continue
        saved = saving(candidate)
        if saved <= 0:
            continue
        chosen.append(candidate.index)
        remaining -= saved
    return chosen


class Estimate:
    """A conversation's tokens from its size in bytes: at ``BYTES_PER_TOKEN`` until the engine
    reports a request's input tokens, then at that request's rate."""

    def __init__(self, bytes_per_token: float = BYTES_PER_TOKEN) -> None:
        if bytes_per_token <= 0:
            raise ValueError("bytes_per_token is above 0")
        self.bytes_per_token = bytes_per_token

    def calibrate(self, request_bytes: int, input_tokens: int) -> None:
        """Take the rate from a request of ``request_bytes`` the engine counted as
        ``input_tokens``. A count of zero or less, on either side, tells nothing and is ignored."""
        if request_bytes > 0 and input_tokens > 0:
            self.bytes_per_token = request_bytes / input_tokens

    def tokens(self, size_bytes: int) -> int:
        """The tokens ``size_bytes`` of conversation is taken to hold, rounded up."""
        return math.ceil(size_bytes / self.bytes_per_token)

    def bytes(self, tokens: int) -> int:
        """The bytes of conversation taken to make ``tokens``, rounded down."""
        return math.floor(tokens * self.bytes_per_token)
