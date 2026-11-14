"""The LM Studio runner against a real LM Studio: opt-in, never in CI (spec: lm-studio-runner, "A
live test runs a real model only when asked"; lmstudio-runner design D14).

    TROUPE_LIVE_LM_STUDIO=1 uv run pytest packages/troupe/tests/test_lm_studio_live.py -s

It runs on the LM Studio at http://127.0.0.1:1234 (``TROUPE_LIVE_LM_STUDIO_ENDPOINT`` points it
elsewhere) with the audition's model (``TROUPE_LIVE_LM_STUDIO_MODEL`` picks another), which must
be downloaded. LM Studio's server must be running with Require Authentication off. It costs nothing
and needs no key. It prints the endpoint, the model, the outcome and the tokens used.
"""

import asyncio
import os
import uuid
from pathlib import Path
from typing import Any

import pytest

from runner_schemas import validate
from troupe.core.artifacts import MemoryArtifactStore
from troupe.core.audition import LM_STUDIO_AUDITION_MODEL
from troupe.core.interim import runner_command, runner_environment
from troupe.core.runners.effects import NoAudit, NoEffectExpected
from troupe.core.runners.host import RunnerCommand, RunRequest, run_actor
from troupe.core.runners.limits import RunLimits
from troupe_plugin_sdk import runner as p

OPT_IN = "TROUPE_LIVE_LM_STUDIO"
ENDPOINT = "TROUPE_LIVE_LM_STUDIO_ENDPOINT"
MODEL = "TROUPE_LIVE_LM_STUDIO_MODEL"
LOCAL = "http://127.0.0.1:1234"
TEST_LIMITS = {"maxTurns": 6, "maxTotalTokens": 50_000}
"""Low limits, as the plugin's tests set: enough for a small local model to write and read back
one file."""
DIRECTION = (
    "Use the Write tool to create out/hello.txt containing exactly: hello\n"
    "Then use the Read tool to read it back, and reply with what it holds."
)

pytestmark = pytest.mark.skipif(
    os.environ.get(OPT_IN) != "1",
    reason=f"opt-in: set {OPT_IN}=1 to run the LM Studio runner against the LM Studio at {LOCAL} "
    f"({ENDPOINT} and {MODEL} point it elsewhere)",
)


def test_a_live_run_writes_and_reads_back_a_file_within_its_limits(tmp_path: Path) -> None:
    endpoint = os.environ.get(ENDPOINT, LOCAL)
    model = os.environ.get(MODEL, LM_STUDIO_AUDITION_MODEL)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    messages: list[tuple[str, dict[str, Any]]] = []
    outcome = asyncio.run(
        run_actor(
            RunnerCommand(
                list(runner_command("lm-studio")),
                cwd=workspace,
                env=runner_environment("lm-studio", os.environ),
            ),
            RunRequest(
                str(uuid.uuid4()),
                DIRECTION,
                workspace,
                dict(TEST_LIMITS),
                effects=p.EffectsDeclaration(write=["out/**"], delete=[], move=[]),
                runtime=p.RunStartRuntime(
                    name="live", endpoint=endpoint, model=model, credential=False
                ),
            ),
            store=MemoryArtifactStore(),
            effect=NoEffectExpected(),
            audit=NoAudit(),
            limits=RunLimits(run_timeout=600.0),
            on_message=lambda direction, message: messages.append((direction, dict(message))),
        )
    )
    for direction, message in messages:
        side = "fromHost" if direction == "sent" else "fromRunner"
        validate(message, f"message.schema.json#/$defs/{side}", runner="runner-lm-studio")
    events = [
        message["params"]
        for direction, message in messages
        if direction == "received" and message.get("method") == "run/event"
    ]
    result = events[-1]
    written = workspace / "out" / "hello.txt"
    print(f"\nendpoint: {endpoint}\nmodel: {model}")
    print(f"outcome: {outcome.outcome}, error: {outcome.error}")
    print(f"events: {[event['type'] for event in events]}")
    print(f"result: {result.get('message')!r}\nusage: {result.get('usage')}")
    assert outcome.outcome == "succeeded", outcome.error
    assert written.read_text(encoding="utf-8").strip() == "hello"
    usage = result.get("usage") or {}
    used = usage.get("inputTokens", 0) + usage.get("outputTokens", 0)
    assert used <= TEST_LIMITS["maxTotalTokens"] * 2, "the run went far past its token budget"
