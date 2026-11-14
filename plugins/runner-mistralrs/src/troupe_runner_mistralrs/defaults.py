"""Every limit and default the mistralrs runner has, each in this one place (in-process-runner
design D9: "Every limit a named setting").

troupe's own limits (contributing/runners.md, "Limits") are troupe's; these are the runner's. Each
is documented in the README, and a test checks every one has a row there.
"""

MAX_TURNS = 50
"""The requests one run may make when the options don't set ``maxTurns``. Reaching it ends the run
with an error result, reason ``turn-limit``."""

MAX_TURNS_LIMIT = 1000
"""The largest ``maxTurns`` the options may set."""

DEFAULT_CONTEXT_LENGTH = 16384
"""The context window, in tokens, when the options don't set ``contextLength``, lowered to the
model's own length (design D7). The same as the Ollama runner's: it holds a direction, a character
and several file reads, and its KV cache fits a laptop."""

CONTEXT_LENGTH_MIN = 2048
"""The smallest ``contextLength`` the options may set: the SDK's tool definitions and the chat
template's preamble take about 1,400 tokens (Qwen3-0.6B), so a smaller window couldn't hold a
request."""

CONTEXT_LENGTH_MAX = 1_048_576
"""The largest ``contextLength`` the options may set. The model's own length lowers it further."""

TOKEN_MARGIN = 256
"""Tokens kept free below the window when the runner bounds an answer (design D7), so an error in
counting the chat template's tokens can't take a request past the window. A first request is
counted before the engine has said how it renders it; later ones are corrected to its count."""

TOOLS_OVERHEAD_TOKENS = 128
"""The tokens the chat template is counted as adding around the tool definitions (its preamble
saying how to call them), which the tokenizer's count of their JSON leaves out (design D7)."""

MESSAGE_OVERHEAD_TOKENS = 8
"""The tokens the chat template is counted as adding around each message (its role markers), which
the tokenizer's count of the message's text leaves out (design D7)."""

TOOL_OUTPUT_SHARE = 0.25
"""The share of the context window one tool result may take, so one large file read can't fill the
window by itself (the Ollama runner's rule)."""

GLOB_PATH_BYTES = 64
"""The bytes one Glob path is taken to need, to scale the SDK's path count to the budget."""

GREP_MATCH_BYTES = 128
"""The bytes one Grep match is taken to need, to scale the SDK's match count to the budget."""

READ_NOTE_BYTES = 128
"""The bytes kept free in a tool result's budget for the note the SDK's Read adds after a capped
read, saying which line to read on from, so it's never cut."""

LOAD_TIMEOUT_SECONDS = 600.0
"""How long loading the model, after run/start is answered, may take before the run ends with an
error result, reason ``configuration`` (design D4). A load can't be stopped, so the runner then
exits. Long, because a large model on a slow disk, or a Mac's first Metal warm-up, takes minutes."""

STOP_GRACE_SECONDS = 2.0
"""How long the runner waits for its worker to stop writing after a cancel, end of input or
shutdown before it exits anyway, abandoning the engine's call (design D2). Well under troupe's
RUNNER_CANCEL_GRACE_SECONDS (10)."""

SUMMARY_MAX_BYTES = 4096
"""The UTF-8 bytes one summary field of an event keeps, before run/start's eventMaxBytes cuts it
further."""
