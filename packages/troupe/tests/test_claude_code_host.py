"""The Claude Code runner through troupe's own host, with a stand-in claude first on its PATH (spec:
claude-code-runner, actor-runners; claude-code-runner design D12)."""

import asyncio
import os
import time
import uuid
from pathlib import Path
from typing import Any

import pytest

import claude_stand_in
from runner_schemas import validate
from troupe.core.artifacts import MemoryArtifactStore
from troupe.core.interim import runner_command
from troupe.core.runners.effects import NoEffectExpected
from troupe.core.runners.host import RunnerCommand, RunRequest, run_actor
from troupe.core.runners.limits import RunLimits
from troupe.core.runners.outcome import RunOutcome

RUNNER = "runner-claude-code"
PASSED_THROUGH = ("COMSPEC", "PATHEXT", "TEMP", "TMP", "TMPDIR")
"""What a real perform would also pass, which the runner needs to start the stand-in on Windows."""


def _command(tmp_path: Path, **settings: str) -> RunnerCommand:
    bin_dir = tmp_path / "bin"
    claude_stand_in.install(bin_dir, **settings)
    env = {"PATH": str(bin_dir)}
    env.update({name: os.environ[name] for name in PASSED_THROUGH if name in os.environ})
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    return RunnerCommand(list(runner_command("claude-code")), cwd=workspace, env=env)


def _run(
    command: RunnerCommand,
    limits: RunLimits,
    *,
    messages: list[tuple[str, dict[str, Any]]] | None = None,
) -> tuple[RunOutcome, MemoryArtifactStore]:
    store = MemoryArtifactStore()
    outcome = asyncio.run(
        run_actor(
            command,
            RunRequest(str(uuid.uuid4()), "say hi", command.cwd, {}),
            store=store,
            effect=NoEffectExpected(),
            limits=limits,
            on_message=None
            if messages is None
            else lambda direction, message: messages.append((direction, dict(message))),
        )
    )
    return outcome, store


@pytest.mark.parametrize("fail_fast", [True, False], ids=["fail fast", "without fail fast"])
@pytest.mark.parametrize("name", claude_stand_in.NAMES)
def test_each_fixture_through_the_claude_code_runner_ends_with_its_stated_outcome(
    name: str, fail_fast: bool, tmp_path: Path
) -> None:
    expected = claude_stand_in.expected(name)
    want = expected if fail_fast else expected["withoutFailFast"]
    command = _command(
        tmp_path, fixture=claude_stand_in.fixture(name), exit=str(expected["exitCode"])
    )
    messages: list[tuple[str, dict[str, Any]]] = []
    outcome, store = _run(
        command, RunLimits(fail_fast_on_auth_retry=fail_fast, cancel_grace=10.0), messages=messages
    )
    assert outcome.outcome == want["outcome"]
    assert (None if outcome.error is None else outcome.error.code) == want["errorCode"]
    for direction, message in messages:
        side = "fromHost" if direction == "sent" else "fromRunner"
        validate(message, f"message.schema.json#/$defs/{side}", runner=RUNNER)
    assert outcome.transcript is not None
    lines = store.read(outcome.transcript).decode("utf-8").splitlines()
    native = claude_stand_in.native_lines(name)
    if fail_fast and want["errorCode"] == "run.authentication":
        assert lines == native[: len(lines)]  # the cancel can land before every line is read
    else:
        assert lines == native


def test_the_stored_transcript_is_the_native_lines_byte_for_byte(tmp_path: Path) -> None:
    name = "success-with-tools"
    command = _command(tmp_path, fixture=claude_stand_in.fixture(name))
    outcome, store = _run(command, RunLimits(cancel_grace=10.0))
    assert outcome.outcome == "succeeded"
    assert outcome.transcript is not None
    native = claude_stand_in.native_lines(name)
    assert store.read(outcome.transcript) == b"".join(
        line.encode("utf-8") + b"\n" for line in native
    )


def test_cancelling_a_claude_code_run_ends_it_cancelled_within_the_grace(tmp_path: Path) -> None:
    lines = tmp_path / "lines.txt"
    lines.write_text(
        '{"type":"system","subtype":"init","tools":[],"model":"m","claude_code_version":"9"}\n',
        encoding="utf-8",
    )
    record = tmp_path / "record.json"
    command = _command(tmp_path, fixture=str(lines), hang="1", record=str(record))
    grace = 10.0

    async def scenario() -> tuple[RunOutcome, float]:
        loop = asyncio.get_running_loop()
        cancel = asyncio.Event()
        task = asyncio.ensure_future(
            run_actor(
                command,
                RunRequest(str(uuid.uuid4()), "say hi", command.cwd, {}),
                store=MemoryArtifactStore(),
                effect=NoEffectExpected(),
                limits=RunLimits(cancel_grace=grace),
                cancel=cancel,
            )
        )
        await loop.run_in_executor(None, claude_stand_in.wait_for_record, record, "argv")
        started = time.monotonic()
        cancel.set()
        outcome = await task
        return outcome, time.monotonic() - started

    outcome, took = asyncio.run(scenario())
    assert outcome.outcome == "cancelled"
    assert outcome.ending.value == "exited"
    assert took < grace


def test_an_ok_result_then_exit_1_fails_as_an_unclean_exit(tmp_path: Path) -> None:
    command = _command(tmp_path, fixture=claude_stand_in.fixture("success-with-tools"), exit="1")
    outcome, _ = _run(command, RunLimits(cancel_grace=10.0))
    assert outcome.outcome == "failed"
    assert outcome.error is not None
    assert outcome.error.code == "run.unclean-exit"
