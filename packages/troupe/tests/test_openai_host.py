"""The OpenAI runner through troupe's own host, against a stand-in service serving the plugin's
fixtures (spec: openai-runner, "Fixtures pair service output with protocol events", "A service's
echo of the credential is masked"; runner-protocol; actor-runners; openai-style-runner design
D13)."""

import asyncio
import uuid
from pathlib import Path
from typing import Any

import pytest

import openai_stand_in
from runner_schemas import validate
from troupe.core.artifacts import MemoryArtifactStore
from troupe.core.interim import runner_command
from troupe.core.runners.effects import NoAudit, NoEffectExpected
from troupe.core.runners.host import RunnerCommand, RunRequest, run_actor
from troupe.core.runners.limits import RunLimits
from troupe.core.runners.outcome import RunOutcome
from troupe_plugin_sdk import runner as p

DIRECTION = "Read notes/todo.txt, then tell me in one line what it says."


def _run(
    name: str, tmp_path: Path
) -> tuple[RunOutcome, MemoryArtifactStore, list[tuple[str, dict[str, Any]]]]:
    provenance = openai_stand_in.load(name, "provenance.json")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    for relative, content in provenance.get("workspace", {}).items():
        target = workspace / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    store = MemoryArtifactStore()
    messages: list[tuple[str, dict[str, Any]]] = []
    key = openai_stand_in.CANARY
    with openai_stand_in.serving(openai_stand_in.fixture_replies(name)) as fake:
        outcome = asyncio.run(
            run_actor(
                RunnerCommand(
                    list(runner_command("openai")),
                    cwd=workspace,
                    env={"TROUPE_RUNTIME_CREDENTIAL": key},
                ),
                RunRequest(
                    str(uuid.uuid4()),
                    DIRECTION,
                    workspace,
                    dict(openai_stand_in.TEST_LIMITS),
                    runtime=p.RunStartRuntime("test", fake.endpoint, provenance["model"], True),
                    credential=key,
                ),
                store=store,
                effect=NoEffectExpected(),
                audit=NoAudit(),
                limits=RunLimits(cancel_grace=10.0),
                on_message=lambda direction, message: messages.append((direction, dict(message))),
            )
        )
    return outcome, store, messages


@pytest.mark.parametrize("name", openai_stand_in.NAMES)
def test_each_fixture_through_the_host_ends_as_its_expected_outcome_and_stores_no_key(
    name: str, tmp_path: Path
) -> None:
    outcome, store, messages = _run(name, tmp_path)
    expected = openai_stand_in.load(name, "expected.json")["outcome"]
    assert outcome.outcome == expected, outcome.error
    if expected == "failed":
        assert outcome.error is not None
        assert outcome.error.code == "run.error-result"
    for direction, message in messages:
        side = "fromHost" if direction == "sent" else "fromRunner"
        validate(message, f"message.schema.json#/$defs/{side}", runner="runner-openai")
    assert outcome.transcript is not None
    stored = store.read(outcome.transcript).decode("utf-8")
    for secret in (openai_stand_in.CANARY, openai_stand_in.ECHO):
        assert secret not in stored


def test_the_stored_transcript_of_a_rejected_key_reads_credential_where_the_service_echoed_it(
    tmp_path: Path,
) -> None:
    outcome, store, _ = _run("rejected-credential", tmp_path)
    assert outcome.transcript is not None
    stored = store.read(outcome.transcript).decode("utf-8")
    assert "Incorrect API key provided: [credential]." in stored


def test_the_three_copies_of_the_test_limits_agree() -> None:
    import importlib.util

    import test_openai_live

    harness = openai_stand_in.PLUGIN / "tests" / "openai_harness.py"
    spec = importlib.util.spec_from_file_location("openai_harness_for_limits", harness)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert openai_stand_in.TEST_LIMITS == module.TEST_LIMITS == test_openai_live.TEST_LIMITS
