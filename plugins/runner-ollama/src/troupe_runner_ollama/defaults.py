"""Every limit and default the Ollama runner has, each in this one place (local-model-runner design
D11).

troupe's own limits (contributing/runners.md, "Limits") are troupe's; these are the runner's. Each
is documented in the README, and a test checks every one has a row there.
"""

DEFAULT_ENDPOINT = "http://127.0.0.1:11434"
"""Where requests go when the options don't set ``endpoint``: Ollama's own default address (design
D10)."""

MAX_TURNS = 50
"""The requests one run may make when the options don't set ``maxTurns``. Reaching it ends the run
with an error result (design D5)."""

MAX_TURNS_LIMIT = 1000
"""The largest ``maxTurns`` the options may set."""

DEFAULT_CONTEXT_LENGTH = 16384
"""The context window, in tokens, sent as ``options.num_ctx`` when the options don't set
``contextLength``, lowered to the model's own maximum (design D15). Never left to Ollama's default,
which differs between versions and machines. 16384 holds a direction, a character and several file
reads, and its KV cache fits a laptop."""

PREFLIGHT_TIMEOUT_SECONDS = 10.0
"""How long each preflight request (version, model) may take before Ollama counts as unreachable
(design D4). Well under troupe's RUNNER_START_TIMEOUT_SECONDS (30), which covers run/start too."""

STREAM_IDLE_TIMEOUT_SECONDS = 300.0
"""How long a request may go without a line from Ollama before it's retried as a network failure
(design D9). Long, because Ollama streams nothing while it loads a model."""

LINE_MAX_BYTES = 16 * 1024 * 1024
"""The longest line the runner reads from Ollama (16 MiB). A longer one is a stream error, never
read whole (design D2)."""

RETRY_MAX_ATTEMPTS = 3
"""The attempts one request gets, the first included, before the run ends with an error (design
D9)."""

RETRY_DELAY_SECONDS = 1.0
"""The delay before the first retry; it doubles for each later one (design D9)."""

STOP_GRACE_SECONDS = 2.0
"""How long the runner waits for its loop to stop after a cancel, end of input or shutdown before it
exits anyway. Well under troupe's RUNNER_CANCEL_GRACE_SECONDS (10) (design D3)."""

SUMMARY_MAX_BYTES = 4096
"""The UTF-8 bytes one summary field of an event keeps, before run/start's eventMaxBytes cuts it
further (design D8)."""
