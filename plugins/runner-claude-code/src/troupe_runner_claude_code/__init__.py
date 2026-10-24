"""troupe's Claude Code runner (spec: claude-code-runner).

It speaks the runner contract (protocol/schemas/runner/) over standard input and output, runs
``claude -p`` with stream-json output, and maps each record onto run events. It imports nothing
from troupe. Run it as ``python -m troupe_runner_claude_code``.
"""

NAME = "claude-code"
__version__ = "0.0.1.dev0"
