"""The Claude Code runner against real Claude Code: opt-in, never in CI (spec: claude-code-runner,
"A live test runs real Claude Code only when asked"; design D12).

Run it with ``TROUPE_LIVE_CLAUDE_CODE=1`` and Claude Code installed. It uses
CLAUDE_CODE_OAUTH_TOKEN or ANTHROPIC_API_KEY when either is set, and otherwise the person's
existing login. It costs at most BUDGET_USD, on a pinned model, and prints which credential it
used and whether CLAUDE.md loaded with no setting sources. The owner runs it, not an agent session:

    TROUPE_LIVE_CLAUDE_CODE=1 uv run pytest packages/troupe/tests/test_claude_code_live.py -s
"""

import asyncio
import os
import uuid
from pathlib import Path

import pytest

from troupe.core.artifacts import MemoryArtifactStore
from troupe.core.interim import runner_command, runner_environment
from troupe.core.runners import protocol as p
from troupe.core.runners.effects import ExpectedFiles
from troupe.core.runners.host import RunnerCommand, RunRequest, run_actor
from troupe.core.runners.limits import RunLimits

OPT_IN = "TROUPE_LIVE_CLAUDE_CODE"
MODEL = "claude-haiku-5-5"
BUDGET_USD = 0.10
DIRECTION = (
    "Use the Write tool to create out/hello.txt containing exactly: hi\n"
    "Then use the Read tool to read it back, and reply with one word: done."
)
MARKER = "PINEAPPLE"
"""What the workspace's CLAUDE.md asks Claude Code to end each reply with, so a reply that ends
with it shows the file loaded."""

pytestmark = pytest.mark.skipif(
    os.environ.get(OPT_IN) != "1",
    reason=f"opt-in: set {OPT_IN}=1 to run real Claude Code (it uses CLAUDE_CODE_OAUTH_TOKEN, "
    "ANTHROPIC_API_KEY or your existing login, and costs up to USD 0.10)",
)


def _credential(env: dict[str, str]) -> str:
    for name in ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY"):
        if env.get(name):
            return name
    return "the existing login"


def test_a_live_run_writes_and_reads_back_a_file_with_only_write_and_read_allowed(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "CLAUDE.md").write_text(
        f"End every reply with the word {MARKER}.\n", encoding="utf-8"
    )
    env = runner_environment("claude-code", os.environ)
    events: list[p.RunEvent] = []

    async def keep(event: p.RunEvent) -> None:
        events.append(event)

    outcome = asyncio.run(
        run_actor(
            RunnerCommand(list(runner_command("claude-code")), cwd=workspace, env=env),
            RunRequest(
                str(uuid.uuid4()),
                DIRECTION,
                workspace,
                {"model": MODEL, "maxBudgetUsd": BUDGET_USD, "allowedTools": ["Write", "Read"]},
            ),
            store=MemoryArtifactStore(),
            effect=ExpectedFiles([workspace / "out" / "hello.txt"]),
            limits=RunLimits(run_timeout=300.0),
            on_event=keep,
        )
    )
    results = [e for e in events if isinstance(e, p.ResultEvent)]
    print(f"\ncredential: {_credential(env)}")
    print(f"outcome: {outcome.outcome} {outcome.error.code if outcome.error else ''}")
    if results:
        loaded = results[0].message.rstrip(". \n").endswith(MARKER)
        print(f"CLAUDE.md loaded with no setting sources: {'yes' if loaded else 'no'}")
    assert outcome.outcome == "succeeded", outcome.error
    assert (workspace / "out" / "hello.txt").read_text(encoding="utf-8").strip() == "hi"
    assert any(isinstance(e, p.ToolCallEvent) and e.tool == "Write" for e in events)
    [result] = results
    assert result.cost_usd is not None
    assert result.cost_usd <= BUDGET_USD
