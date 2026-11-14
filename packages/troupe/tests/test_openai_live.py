"""The OpenAI runner against a real Responses API service: opt-in, never in CI (spec: openai-runner,
"A live test runs a real service only when asked"; openai-style-runner design D13).

    TROUPE_LIVE_OPENAI=1 uv run pytest packages/troupe/tests/test_openai_live.py -s

By default it runs on OpenAI with the audition's model, and needs ``OPENAI_API_KEY``: a few cents,
within TEST_LIMITS. ``TROUPE_LIVE_OPENAI_ENDPOINT`` and ``TROUPE_LIVE_OPENAI_MODEL`` point it
elsewhere, such as local Ollama's ``http://127.0.0.1:11434/v1``, which costs nothing and needs no
key. It sends ``OPENAI_API_KEY`` to any endpoint that isn't on this machine, so point it only at a
service that key is for. It prints the endpoint, the model, the outcome and the tokens used.
"""

import asyncio
import os
import uuid
from pathlib import Path
from typing import Any

import pytest

from runner_schemas import validate
from troupe.core.artifacts import MemoryArtifactStore
from troupe.core.audition import OPENAI_AUDITION_MODEL
from troupe.core.interim import runner_command, runner_environment
from troupe.core.runners.effects import NoAudit, NoEffectExpected
from troupe.core.runners.host import RunnerCommand, RunRequest, run_actor
from troupe.core.runners.limits import RunLimits
from troupe.core.runtimes import is_loopback
from troupe_plugin_sdk import runner as p

OPT_IN = "TROUPE_LIVE_OPENAI"
ENDPOINT = "TROUPE_LIVE_OPENAI_ENDPOINT"
MODEL = "TROUPE_LIVE_OPENAI_MODEL"
KEY = "OPENAI_API_KEY"
OPENAI = "https://api.openai.com/v1"
TEST_LIMITS = {"maxTurns": 5, "maxTotalTokens": 20_000}
"""The plugin's test limits (openai-style-runner design D7): a few cents on a real service."""
DIRECTION = (
    "Use the Write tool to create out/hello.txt containing exactly: hello\n"
    "Then use the Read tool to read it back, and reply with what it holds."
)

pytestmark = pytest.mark.skipif(
    os.environ.get(OPT_IN) != "1",
    reason=f"opt-in: set {OPT_IN}=1 to run the OpenAI runner against {OPENAI} with {KEY} "
    f"({ENDPOINT} and {MODEL} point it elsewhere, such as local Ollama's /v1)",
)


def test_a_live_run_writes_and_reads_back_a_file_within_its_budget(tmp_path: Path) -> None:
    endpoint = os.environ.get(ENDPOINT, OPENAI)
    model = os.environ.get(MODEL, OPENAI_AUDITION_MODEL)
    key = os.environ.get(KEY, "")
    local = is_loopback(endpoint)
    if not local and not key:
        pytest.fail(f"{KEY} isn't set, and {endpoint} needs a key")
    credential = None if local else key
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    env = runner_environment("openai", os.environ)
    if credential is not None:
        env["TROUPE_RUNTIME_CREDENTIAL"] = credential
    messages: list[tuple[str, dict[str, Any]]] = []
    outcome = asyncio.run(
        run_actor(
            RunnerCommand(list(runner_command("openai")), cwd=workspace, env=env),
            RunRequest(
                str(uuid.uuid4()),
                DIRECTION,
                workspace,
                dict(TEST_LIMITS),
                effects=p.EffectsDeclaration(write=["out/**"], delete=[], move=[]),
                runtime=p.RunStartRuntime(
                    name="live", endpoint=endpoint, model=model, credential=credential is not None
                ),
                credential=credential,
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
        validate(message, f"message.schema.json#/$defs/{side}", runner="runner-openai")
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
    used = sum(
        usage.get(k, 0)
        for k in ("inputTokens", "outputTokens", "cacheReadTokens", "cacheWriteTokens")
    )
    assert used <= TEST_LIMITS["maxTotalTokens"] * 2, "the run went far past its token budget"
    if key:
        for _direction, message in messages:
            assert key not in str(message)
