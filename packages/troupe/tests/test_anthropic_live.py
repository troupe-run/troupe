"""The Anthropic runner against a real Messages API service: opt-in, never in CI (spec:
anthropic-runner, "Live tests run a real service only when asked"; anthropic-runner design D14).

    TROUPE_LIVE_ANTHROPIC=1 uv run pytest packages/troupe/tests/test_anthropic_live.py -s
    TROUPE_LIVE_ANTHROPIC_LOCAL=1 TROUPE_LIVE_ANTHROPIC_ENDPOINT=http://127.0.0.1:1234 \
        TROUPE_LIVE_ANTHROPIC_MODEL=google/gemma-4-e4b \
        uv run pytest packages/troupe/tests/test_anthropic_live.py -s

The first runs on Claude's API with the audition's model, and needs ``ANTHROPIC_API_KEY``: a few
cents, within TEST_LIMITS. The second runs on a local engine that serves the Messages API, named by
``TROUPE_LIVE_ANTHROPIC_ENDPOINT`` and ``TROUPE_LIVE_ANTHROPIC_MODEL``, with no key; it costs
nothing. Each prints the endpoint, the model, the outcome and the tokens used.
"""

import asyncio
import os
import uuid
from pathlib import Path
from typing import Any

import pytest

from runner_schemas import validate
from troupe.core.artifacts import MemoryArtifactStore
from troupe.core.audition import ANTHROPIC_AUDITION_MODEL
from troupe.core.interim import runner_command, runner_environment
from troupe.core.runners.effects import NoAudit, NoEffectExpected
from troupe.core.runners.host import RunnerCommand, RunRequest, run_actor
from troupe.core.runners.limits import RunLimits
from troupe_plugin_sdk import runner as p

CLAUDE = "TROUPE_LIVE_ANTHROPIC"
LOCAL = "TROUPE_LIVE_ANTHROPIC_LOCAL"
ENDPOINT = "TROUPE_LIVE_ANTHROPIC_ENDPOINT"
MODEL = "TROUPE_LIVE_ANTHROPIC_MODEL"
KEY = "ANTHROPIC_API_KEY"
CLAUDES_API = "https://api.anthropic.com"
TEST_LIMITS = {"maxTurns": 5, "maxTotalTokens": 20_000}
"""The plugin's test limits: a few cents on Claude's API."""
DIRECTION = (
    "Use the Write tool to create out/hello.txt containing exactly: hello\n"
    "Then use the Read tool to read it back, and reply with what it holds."
)


def _live_run(tmp_path: Path, endpoint: str, model: str, credential: str | None) -> None:
    """Run the runner through troupe's host on ``endpoint`` and check it wrote and read back the
    file within its budget, every message valid, and the key nowhere in them."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    env = runner_environment("anthropic", os.environ)
    if credential is not None:
        env["TROUPE_RUNTIME_CREDENTIAL"] = credential
    messages: list[tuple[str, dict[str, Any]]] = []
    outcome = asyncio.run(
        run_actor(
            RunnerCommand(list(runner_command("anthropic")), cwd=workspace, env=env),
            RunRequest(
                str(uuid.uuid4()),
                DIRECTION,
                workspace,
                dict(TEST_LIMITS),
                effects=p.EffectsDeclaration(write=["out/**"], delete=[], move=[]),
                runtime=p.RunStartRuntime("live", endpoint, model, credential is not None),
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
        validate(message, f"message.schema.json#/$defs/{side}", runner="runner-anthropic")
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
    if credential:
        for _direction, message in messages:
            assert credential not in str(message)


@pytest.mark.skipif(
    os.environ.get(CLAUDE) != "1",
    reason=f"opt-in: set {CLAUDE}=1 to run the Anthropic runner against {CLAUDES_API} with {KEY}",
)
def test_a_live_run_on_claudes_api_writes_and_reads_back_a_file_within_its_budget(
    tmp_path: Path,
) -> None:
    key = os.environ.get(KEY, "")
    if not key:
        pytest.fail(f"{KEY} isn't set, and {CLAUDES_API} needs a key")
    _live_run(tmp_path, CLAUDES_API, ANTHROPIC_AUDITION_MODEL, key)


@pytest.mark.skipif(
    os.environ.get(LOCAL) != "1",
    reason=f"opt-in: set {LOCAL}=1, {ENDPOINT} (a local engine's server root, such as LM Studio's "
    f"http://127.0.0.1:1234) and {MODEL} to run the Anthropic runner on a local engine",
)
def test_a_live_run_on_a_local_engine_writes_and_reads_back_a_file_within_its_budget(
    tmp_path: Path,
) -> None:
    endpoint, model = os.environ.get(ENDPOINT), os.environ.get(MODEL)
    if not endpoint or not model:
        pytest.fail(f"{LOCAL}=1 needs {ENDPOINT} and {MODEL}")
    _live_run(tmp_path, endpoint, model, None)
