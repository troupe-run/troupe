"""Every limit the Claude Code runner has, each with its default in this one place (design D11).

troupe's own limits (contributing/runners.md, "Limits") are troupe's; these are the runner's.
"""

DEFAULT_MAX_BUDGET_USD = 5.0
"""A run's spend, in US dollars, when the options don't set maxBudgetUsd (owner, 2026-10-24)."""

SUMMARY_MAX_BYTES = 4096
"""The UTF-8 bytes one summary field of an event keeps, before run/start's eventMaxBytes cuts it
further."""

CLAUDE_STOP_GRACE_SECONDS = 5.0
"""How long Claude Code has to exit after it is asked to stop before it is killed. Below troupe's
default RUNNER_CANCEL_GRACE_SECONDS (10), so the runner finishes its own stop first."""

CLAUDE_EXIT_WAIT_SECONDS = 5.0
"""How long the runner waits for Claude Code to exit after its result before stopping it."""
