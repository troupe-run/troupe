"""The Ollama runner through troupe's own host, against a stand-in Ollama serving the plugin's
fixtures (spec: ollama-runner, runner-protocol, actor-runners; local-model-runner design D7, D9,
D12)."""

import asyncio
import json
import sys
import time
import uuid
from pathlib import Path
from typing import Any

import pytest

import ollama_stand_in
from runner_schemas import validate
from troupe.core.artifacts import MemoryArtifactStore
from troupe.core.interim import runner_command
from troupe.core.runners.effects import NoAudit, NoEffectExpected
from troupe.core.runners.host import RunnerCommand, RunRequest, run_actor
from troupe.core.runners.limits import RunLimits
from troupe.core.runners.outcome import RunOutcome, TranscriptFormat
from troupe_plugin_sdk import runner as p

RUNNER = "runner-ollama"
REFUSALS = {
    "model-not-found": "ollama.model-not-found",
    "no-tools-capability": "ollama.model-without-tools",
}
RUNS = [name for name in ollama_stand_in.NAMES if name not in REFUSALS]
NOTES = {"notes.txt": "A line of notes.\n" * 200}
FILES = {
    "context-overflow": NOTES,
    "context-compaction-exhausted": NOTES,
    "context-compacted": {
        name: "".join(f"The {topic} log, entry {n}: all quiet.\n" for n in range(1, 81))
        for name, topic in (("a.txt", "lighthouse"), ("b.txt", "harbour"), ("c.txt", "ferry"))
    },
}
"""The files each fixture's workspace starts with, as plugins/runner-ollama's capture tool made
them (its fixture_replay.FILES, which its tests check against the tool)."""


def _workspace(tmp_path: Path, name: str) -> Path:
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    for relative, content in FILES.get(name, {}).items():
        (workspace / relative).write_text(content, encoding="utf-8")
    return workspace


def _run(
    name: str, tmp_path: Path, endpoint: str
) -> tuple[RunOutcome, MemoryArtifactStore, list[tuple[str, dict[str, Any]]], Path]:
    provenance = ollama_stand_in.provenance(name)
    workspace = _workspace(tmp_path, name)
    # A backslash in the name makes the path need escaping on every OS, as a Windows path does
    # (where a backslash is the separator, so the plain name is enough).
    scratch = tmp_path / ("scratch" if sys.platform == "win32" else "scra\\tch")
    scratch.mkdir()
    effects = provenance.get("effects") or {}
    store = MemoryArtifactStore()
    messages: list[tuple[str, dict[str, Any]]] = []
    outcome = asyncio.run(
        run_actor(
            RunnerCommand(list(runner_command("ollama")), cwd=workspace),
            RunRequest(
                str(uuid.uuid4()),
                provenance.get("direction", ""),
                workspace,
                provenance["options"],
                runtime=p.RunStartRuntime(
                    name="ollama", endpoint=endpoint, model=provenance["model"], credential=False
                ),
                effects=p.EffectsDeclaration(
                    write=effects.get("write", []),
                    delete=effects.get("delete", []),
                    move=effects.get("move", []),
                ),
                scratch=scratch,
                on_context_full=provenance.get("onContextFull", "fail"),
            ),
            store=store,
            effect=NoEffectExpected(),
            audit=NoAudit(),
            limits=RunLimits(cancel_grace=10.0),
            on_message=lambda direction, message: messages.append((direction, dict(message))),
        )
    )
    return outcome, store, messages, scratch


def _stored(outcome: RunOutcome, store: MemoryArtifactStore, scratch: Path) -> list[str]:
    """The stored transcript's lines, with ``<scratch>`` for the run's scratch path. Each line is
    a record framed with its kind, so the path is scrubbed in the record and the line framed again,
    as the fixture's were: in the framed line, a path that needs escaping is escaped twice."""
    assert outcome.transcript is not None
    assert outcome.transcript_format is TranscriptFormat.KINDS
    lines = []
    for text in store.read(outcome.transcript).decode("utf-8").splitlines():
        line = json.loads(text)
        line["record"] = line["record"].replace(json.dumps(str(scratch))[1:-1], "<scratch>")
        lines.append(json.dumps(line, ensure_ascii=False, separators=(",", ":")))
    return lines


@pytest.mark.parametrize("name", RUNS)
def test_each_fixture_through_the_host_ends_as_its_result_says_storing_its_transcript(
    name: str, tmp_path: Path
) -> None:
    with ollama_stand_in.serving(name) as fake:
        outcome, store, messages, scratch = _run(name, tmp_path, fake.url)
    result = ollama_stand_in.events(name)[-1]
    if result["status"] == "ok":
        assert (outcome.outcome, outcome.error) == ("succeeded", None)
    else:
        assert outcome.outcome == "failed"
        assert outcome.error is not None
        assert outcome.error.code == "run.error-result"
    for direction, message in messages:
        side = "fromHost" if direction == "sent" else "fromRunner"
        validate(message, f"message.schema.json#/$defs/{side}", runner=RUNNER)
    assert _stored(outcome, store, scratch) == ollama_stand_in.records(name)


@pytest.mark.parametrize("name", sorted(REFUSALS))
def test_a_preflight_refusal_ends_the_run_could_not_start_with_the_runners_code(
    name: str, tmp_path: Path
) -> None:
    with ollama_stand_in.serving(name) as fake:
        outcome, _, _, _ = _run(name, tmp_path, fake.url)
    assert outcome.outcome == "could-not-start"
    assert outcome.error is not None
    assert REFUSALS[name] in f"{outcome.error.code} {outcome.error.problem} {outcome.error.details}"


def test_an_ollama_too_old_ends_the_run_could_not_start_naming_the_requirement(
    tmp_path: Path,
) -> None:
    module = ollama_stand_in._fake()
    old = module.Settings(version="0.12.5")
    fake = module.FakeOllama([], old).start()
    try:
        outcome, _, _, _ = _run("success-with-tools", tmp_path, fake.url)
    finally:
        fake.stop()
    assert outcome.outcome == "could-not-start"
    assert outcome.error is not None
    assert "runner.requirement-unmet" in f"{outcome.error.code} {outcome.error.details}"


def test_cancelling_an_ollama_run_mid_stream_ends_it_cancelled_within_the_grace(
    tmp_path: Path,
) -> None:
    grace = 10.0
    workspace = _workspace(tmp_path, "slow")

    async def scenario(endpoint: str, fake: Any) -> tuple[RunOutcome, float]:  # noqa: ANN401
        loop = asyncio.get_running_loop()
        cancel = asyncio.Event()
        task = asyncio.ensure_future(
            run_actor(
                RunnerCommand(list(runner_command("ollama")), cwd=workspace),
                RunRequest(
                    str(uuid.uuid4()),
                    "think",
                    workspace,
                    {},
                    runtime=p.RunStartRuntime(
                        name="ollama", endpoint=endpoint, model="fake", credential=False
                    ),
                ),
                store=MemoryArtifactStore(),
                effect=NoEffectExpected(),
                audit=NoAudit(),
                limits=RunLimits(cancel_grace=grace),
                cancel=cancel,
            )
        )
        while not fake.chats():
            await asyncio.sleep(0.02)
        await loop.run_in_executor(None, time.sleep, 0.2)
        started = time.monotonic()
        cancel.set()
        outcome = await task
        return outcome, time.monotonic() - started

    with ollama_stand_in.slow() as fake:
        outcome, took = asyncio.run(scenario(fake.url, fake))
        assert fake.closed_by_client.wait(5)
    assert outcome.outcome == "cancelled"
    assert outcome.ending.value == "exited"
    assert took < grace


# The contract's amended requirements (spec: runner-protocol), through the host.


def test_a_runners_tool_message_is_a_stored_record_before_the_next_answers_lines(
    tmp_path: Path,
) -> None:
    with ollama_stand_in.serving("success-with-tools") as fake:
        outcome, store, _, scratch = _run("success-with-tools", tmp_path, fake.url)
    lines = [json.loads(line) for line in _stored(outcome, store, scratch)]
    stored = [json.loads(line["record"]) for line in lines]
    tool = next(i for i, r in enumerate(stored) if r.get("role") == "tool")
    first_line_after = next(i for i, r in enumerate(stored) if i > tool and "done" in r)
    assert tool < first_line_after
    assert lines[tool]["kind"] == "sent"
    assert lines[first_line_after]["kind"] == "received"
    assert "Wrote" in stored[tool]["content"]


def test_history_sent_again_is_stored_once(tmp_path: Path) -> None:
    with ollama_stand_in.serving("success-with-tools") as fake:
        outcome, store, _, scratch = _run("success-with-tools", tmp_path, fake.url)
        assert len(fake.chats()) == 2
    direction = ollama_stand_in.provenance("success-with-tools")["direction"]
    stored = "\n".join(json.loads(line)["record"] for line in _stored(outcome, store, scratch))
    assert stored.count(json.dumps(direction)[1:-1]) == 1


def test_a_dropped_connection_gives_a_network_retry_before_the_next_attempt(
    tmp_path: Path,
) -> None:
    with ollama_stand_in.serving("network-retries") as fake:
        outcome, _, messages, _ = _run("network-retries", tmp_path, fake.url)
    events = [
        m["params"] for d, m in messages if d == "received" and m.get("method") == "run/event"
    ]
    retry = next(e for e in events if e["type"] == "retry")
    assert (retry["reason"], retry["attempt"]) == ("network", 1)
    assert outcome.outcome == "succeeded"
