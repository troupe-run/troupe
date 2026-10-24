"""Real Claude Code output, replayed by the scripted runner through the run host (spec:
claude-code-runner, "Fixtures replay through the contract")."""

import asyncio
import json
import sys
import uuid
from pathlib import Path
from typing import Any

import pytest

from runner_schemas import validate
from troupe.core.artifacts import MemoryArtifactStore
from troupe.core.runners.effects import NoEffectExpected
from troupe.core.runners.host import RunnerCommand, RunRequest, run_actor
from troupe.core.runners.limits import RunLimits
from troupe.core.runners.outcome import RunOutcome

FIXTURES = Path(__file__).resolve().parents[3] / "plugins" / "runner-claude-code" / "fixtures"
NAMES = sorted(path.name for path in (FIXTURES / "claude-code").iterdir() if path.is_dir())


def _replay(name: str, limits: RunLimits, tmp_path: Path) -> tuple[RunOutcome, list[Any], bytes]:
    fixture = FIXTURES / "claude-code" / name
    expected = json.loads((fixture / "expected.json").read_text(encoding="utf-8"))
    script = {
        "steps": [{"replay": str(fixture / "recording.jsonl")}, {"exit": expected["exitCode"]}]
    }
    messages: list[Any] = []
    store = MemoryArtifactStore()
    outcome = asyncio.run(
        run_actor(
            RunnerCommand([sys.executable, "-m", "troupe_runner_scripted"], cwd=tmp_path),
            RunRequest(str(uuid.uuid4()), "replay", tmp_path, {"script": script}),
            store=store,
            effect=NoEffectExpected(),
            limits=limits,
            on_message=lambda direction, message: messages.append((direction, dict(message))),
        )
    )
    assert outcome.transcript is not None
    return outcome, messages, store.read(outcome.transcript)


@pytest.mark.parametrize("fail_fast", [True, False], ids=["fail fast", "without fail fast"])
@pytest.mark.parametrize("name", NAMES)
def test_each_fixture_replays_through_the_contract_to_its_stated_outcome(
    name: str, fail_fast: bool, tmp_path: Path
) -> None:
    expected = json.loads(
        (FIXTURES / "claude-code" / name / "expected.json").read_text(encoding="utf-8")
    )
    want = expected if fail_fast else expected["withoutFailFast"]
    outcome, messages, transcript = _replay(
        name, RunLimits(fail_fast_on_auth_retry=fail_fast, cancel_grace=3.0), tmp_path
    )
    assert outcome.outcome == want["outcome"]
    assert (None if outcome.error is None else outcome.error.code) == want["errorCode"]
    for direction, message in messages:
        validate(
            message,
            "message.schema.json#/$defs/" + ("fromHost" if direction == "sent" else "fromRunner"),
        )
    native = [
        json.loads(line)["transcript"]
        for line in (FIXTURES / "claude-code" / name / "recording.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if "transcript" in json.loads(line)
    ]
    if fail_fast and want["errorCode"] == "run.authentication":
        assert transcript.decode().splitlines() == native[: len(transcript.decode().splitlines())]
    else:
        assert transcript.decode().splitlines() == native
