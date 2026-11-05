"""Every limit and fixed text the OpenAI runner has, each in this one place
(openai-style-runner design D6, D7, D10).

troupe's own limits (contributing/runners.md, "Limits") are troupe's; these are the runner's. The
run limits are sized for real work. Tests never run on them: they set low limits through the options
(design D7).
"""

DEFAULT_MAX_TURNS = 50
"""Requests in a run, when the options don't set maxTurns."""

DEFAULT_MAX_TOTAL_TOKENS = 1_000_000
"""Input plus output tokens over a run, as the service reports them, when the options don't set
maxTotalTokens. With no price from the service, this is what bounds a run's spend."""

MAX_ATTEMPTS = 5
"""Attempts at one request, the first included, before a failure that retrying might fix ends the
run."""

RETRY_BASE_DELAY_SECONDS = 1.0
"""The first retry's delay. Each later retry doubles it, up to RETRY_MAX_DELAY_SECONDS."""

RETRY_MAX_DELAY_SECONDS = 60.0
"""The longest the runner waits before a retry. A Retry-After longer than this ends the run rather
than being waited out."""

CONNECT_TIMEOUT_SECONDS = 30.0
"""Connecting to the service and getting its response's status."""

STREAM_TIMEOUT_SECONDS = 120.0
"""Silence between two reads of a response's stream. Past it, the stream counts as broken."""

SUMMARY_MAX_BYTES = 4096
"""The UTF-8 bytes one summary field of an event keeps, before run/start's eventMaxBytes cuts it
further."""

STOP_GRACE_SECONDS = 5.0
"""How long the tool loop has to stop after a cancel before the runner exits anyway. Below troupe's
default RUNNER_CANCEL_GRACE_SECONDS (10), so the runner finishes its own stop first."""

TRANSCRIPT_HEADERS: tuple[str, ...] = ("retry-after", "x-request-id")
"""The response headers the transcript keeps, by lower-case name, besides those starting with one of
TRANSCRIPT_HEADER_PREFIXES. Request headers are never kept (design D10)."""

TRANSCRIPT_HEADER_PREFIXES: tuple[str, ...] = ("x-ratelimit-",)
"""Response header name prefixes the transcript keeps."""

INSTRUCTIONS = (
    "You are an actor run by troupe. You work in a workspace, and only through the tools you are "
    "offered: read, search and change files with them, by paths relative to the workspace. A tool "
    "call that is refused says why; don't repeat it unchanged. When the work is done, reply "
    "without calling a tool: that reply ends the run, and is its summary, so say what you did."
)
"""The runner's fixed instructions: the first part of every run's system message, before the
actor's character (design D6)."""

STREAM_LINE_MAX_BYTES = 16 * 1024 * 1024
"""The longest one line of a response's stream may be. A longer one counts as a broken stream."""

ERROR_BODY_MAX_BYTES = 1024 * 1024
"""How much of a non-streamed response's body (an error, say) the runner reads."""
