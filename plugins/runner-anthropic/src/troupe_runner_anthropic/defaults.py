"""Every limit and fixed text the Anthropic runner has, each in this one place (anthropic-runner
design D5, D10).

troupe's own limits (contributing/runners.md, "Limits") are troupe's; these are the runner's. The
run limits are sized for real work. Tests never run on them: they set low limits through the
options.
"""

DEFAULT_MAX_TURNS = 50
"""Requests in a run, when the options don't set maxTurns."""

DEFAULT_MAX_TOTAL_TOKENS = 1_000_000
"""Input, cache and output tokens over a run, as the service reports them, when the options don't
set maxTotalTokens. With no price from the service, this is what bounds a run's spend."""

DEFAULT_MAX_OUTPUT_TOKENS = 16_000
"""Each request's max_tokens, which the Messages API requires, when the options don't set
maxOutputTokens (design D5)."""

MAX_ATTEMPTS = 5
"""Attempts at one request, the first included, before a failure that retrying might fix ends the
run. The library's own retries are off (design D10)."""

RETRY_BASE_DELAY_SECONDS = 1.0
"""The first retry's delay. Each later retry doubles it, up to RETRY_MAX_DELAY_SECONDS."""

RETRY_MAX_DELAY_SECONDS = 60.0
"""The longest the runner waits before a retry. A rate limit's Retry-After longer than this ends
the run rather than being waited out; a server error's is cut to it."""

CONNECT_TIMEOUT_SECONDS = 30.0
"""Connecting to the service, the library's connect and pool timeouts (design D10)."""

WRITE_TIMEOUT_SECONDS = 30.0
"""Sending a request's body, the library's write timeout."""

STREAM_TIMEOUT_SECONDS = 120.0
"""Silence while reading a response, its status or its stream, the library's read timeout. Past it,
the request counts as broken and is retried."""

SUMMARY_MAX_BYTES = 4096
"""The UTF-8 bytes one summary field of an event keeps, before run/start's eventMaxBytes cuts it
further."""

STOP_GRACE_SECONDS = 5.0
"""How long the tool loop has to stop after a cancel, between requests, before the runner exits
anyway. Below troupe's default RUNNER_CANCEL_GRACE_SECONDS (10), so the runner finishes first. A
request in flight isn't waited for: the runner ends its process at once (design D9)."""

LIBRARY_LOG_MAX_BYTES = 2048
"""The UTF-8 bytes of one library warning the runner passes to standard error."""

TRANSCRIPT_HEADERS: tuple[str, ...] = (
    "content-type",
    "request-id",
    "retry-after",
    "retry-after-ms",
    "x-should-retry",
)
"""The response headers the transcript keeps, by lower-case name, besides those starting with one of
TRANSCRIPT_HEADER_PREFIXES, in each response's ``note`` record. Request headers are never kept
(design D11)."""

TRANSCRIPT_HEADER_PREFIXES: tuple[str, ...] = ("anthropic-ratelimit-",)
"""Response header name prefixes the transcript keeps."""

INSTRUCTIONS = (
    "You are an actor run by troupe. You work in a workspace, and only through the tools you are "
    "offered: read, search and change files with them, by paths relative to the workspace. A tool "
    "call that is refused says why; don't repeat it unchanged. When the work is done, reply "
    "without calling a tool: that reply ends the run, and is its summary, so say what you did."
)
"""The runner's fixed instructions: the first part of every run's system prompt, before the
actor's character."""
