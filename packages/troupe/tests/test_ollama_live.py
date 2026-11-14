"""The Ollama runner against a real Ollama: opt-in, never in CI (spec: ollama-runner, "A live test
runs a real model only when asked"; local-model-runner design D14).

Run it with ``TROUPE_LIVE_OLLAMA=1``, Ollama running at its default address, and the model pulled:
``TROUPE_LIVE_OLLAMA_MODEL`` names it, or the audition's model when it isn't set.

    TROUPE_LIVE_OLLAMA=1 uv run pytest packages/troupe/tests/test_ollama_live.py -s

It asserts what the runner controls: every message keeps the contract, the run reaches a result,
and its outcome is succeeded or failed, never crashed. It prints whether the model wrote the file,
but doesn't assert it: small models are flaky at tool use (#16, option B).
"""

import asyncio
import os
import uuid
from pathlib import Path
from typing import Any

import pytest

from runner_schemas import validate
from troupe.core.artifacts import MemoryArtifactStore
from troupe.core.audition import OLLAMA_AUDITION_MODEL
from troupe.core.defaults import RUNTIMES
from troupe.core.interim import runner_command, runner_environment
from troupe.core.runners.effects import NoAudit, NoEffectExpected
from troupe.core.runners.host import RunnerCommand, RunRequest, run_actor
from troupe.core.runners.limits import RunLimits
from troupe_plugin_sdk import runner as p

OPT_IN = "TROUPE_LIVE_OLLAMA"
OLLAMA_ENDPOINT = str(RUNTIMES["ollama"]["endpoint"])
"""The built-in ollama runtime's endpoint: Ollama's default address."""
MODEL = "TROUPE_LIVE_OLLAMA_MODEL"
DIRECTION = "Use the Write tool to create out/hello.txt containing exactly: hello"

pytestmark = pytest.mark.skipif(
    os.environ.get(OPT_IN) != "1",
    reason=f"opt-in: set {OPT_IN}=1 to run a real model through Ollama at its default address "
    f"({MODEL} names the model; the audition's, {OLLAMA_AUDITION_MODEL}, when it isn't set)",
)


def test_a_live_run_keeps_the_contract_and_reaches_a_result(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    model = os.environ.get(MODEL, OLLAMA_AUDITION_MODEL)
    messages: list[tuple[str, dict[str, Any]]] = []
    outcome = asyncio.run(
        run_actor(
            RunnerCommand(
                list(runner_command("ollama")),
                cwd=workspace,
                env=runner_environment("ollama", os.environ),
            ),
            RunRequest(
                str(uuid.uuid4()),
                DIRECTION,
                workspace,
                {"temperature": 0, "seed": 1},
                effects=p.EffectsDeclaration(write=["out/**"], delete=[], move=[]),
                runtime=p.RunStartRuntime(
                    name="ollama", endpoint=OLLAMA_ENDPOINT, model=model, credential=False
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
        validate(message, f"message.schema.json#/$defs/{side}", runner="runner-ollama")
    events = [
        message["params"]
        for direction, message in messages
        if direction == "received" and message.get("method") == "run/event"
    ]
    written = workspace / "out" / "hello.txt"
    print(f"\nmodel: {model}")
    print(f"outcome: {outcome.outcome}, error: {outcome.error}")
    print(f"events: {[event['type'] for event in events]}")
    print(
        f"wrote out/hello.txt: {written.read_text(encoding='utf-8')!r}"
        if written.exists()
        else "wrote no out/hello.txt"
    )
    assert events[-1]["type"] == "result"
    assert outcome.outcome in ("succeeded", "failed")
