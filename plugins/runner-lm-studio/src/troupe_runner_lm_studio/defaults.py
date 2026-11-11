"""Every limit and fixed text the LM Studio runner has, each in this one place (lmstudio-runner
design D5, D7, D10).

troupe's own limits (contributing/runners.md, "Limits") are troupe's; these are the runner's. Every
timeout the library applies is set from one of these, never left to the library's default
(runner-protocol, "Retries follow troupe's named limits, not the library's"). The run limits are
sized for real work; tests set low ones through the options.
"""

DEFAULT_MAX_TURNS = 20
"""Prediction rounds in a run, when the options don't set maxTurns. Every round is offered the
tools; a run whose last round still asks for one ends at the turn limit once its calls are done."""

DEFAULT_MAX_TOTAL_TOKENS = 200_000
"""Prompt plus predicted tokens over a run, as LM Studio reports them for each round, when the
options don't set maxTotalTokens. Checked after each round's tool calls have finished."""

DEFAULT_CONTEXT_LENGTH = 16_384
"""The context length a model is loaded with when the run loads it, when the options don't set
contextLength. A model already loaded keeps its own (design D5)."""

CHECK_TIMEOUT_SECONDS = 10.0
"""The pre-run check: reaching LM Studio and listing its downloaded models, before run/start is
answered. The library's own greeting check has a fixed one-second timeout of its own, inside
this."""

MESSAGE_TIMEOUT_SECONDS = 120.0
"""Waiting for LM Studio's next message on the websocket. Load progress, prompt-processing progress
and prediction fragments each count, so only real silence reaches it. Set as the library's
timeout in place of its default (60 seconds)."""

WEBSOCKET_CLOSE_TIMEOUT_SECONDS = 2.0
"""Closing the websocket. Set in place of the library's own (10 seconds), so a stop isn't held up
by it."""

MAX_ATTEMPTS = 3
"""Attempts at reaching LM Studio and starting the run, the first included, while no tool call has
run. After one has, nothing is retried (design D10)."""

RETRY_BASE_DELAY_SECONDS = 1.0
"""The first retry's delay. Each later retry doubles it, up to RETRY_MAX_DELAY_SECONDS."""

RETRY_MAX_DELAY_SECONDS = 10.0
"""The longest the runner waits before a retry."""

SUMMARY_MAX_BYTES = 4096
"""The UTF-8 bytes one summary field of an event keeps, before run/start's eventMaxBytes cuts it
further."""

STOP_GRACE_SECONDS = 5.0
"""How long the run has to stop after a cancel before the runner exits anyway. Below troupe's
default RUNNER_CANCEL_GRACE_SECONDS (10), so the runner finishes its own stop first."""

INSTRUCTIONS = (
    "You are working on a software project as one member of a team. You can read and change "
    "files in the project's workspace only through the tools you are given. Paths are relative to "
    "the workspace. Do what the user asks, using the tools, then reply with a short summary of "
    "what you did."
)
"""The system prompt's fixed part, before the actor's character (design D7). Where the model may
work is in each tool's own description, which the SDK writes."""
