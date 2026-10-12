"""Conformance checks any runner can be run against (spec: actor-runners; design D13).

Each check starts the runner afresh. ``options`` are the runner's own run/start options for a short
run that succeeds, so the checks work for runners whose behaviour can't be scripted (Claude Code is
given a cheap prompt). A check passes or fails with a problem naming what the runner did.
"""

import asyncio
import contextlib
import json
import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path

from troupe.core import defaults
from troupe.core.artifacts import MemoryArtifactStore
from troupe.core.runners import protocol as p
from troupe.core.runners.effects import NoEffectExpected
from troupe.core.runners.host import RunnerCommand, RunRequest, run_actor
from troupe.core.runners.limits import RunLimits
from troupe.core.runners.outcome import Outcome
from troupe.platform import processes


@dataclass(frozen=True)
class CheckResult:
    name: str
    passed: bool
    problem: str | None = None


class _Failed(Exception):  # noqa: N818 - a check's verdict, not a Python failure
    pass


class _Driver:
    """Talks to a runner directly, for checks the run host would never let happen."""

    def __init__(self, child: processes.ChildProcess, limits: RunLimits) -> None:
        self.child = child
        self.limits = limits
        self.next_id = 1

    async def send(self, method: str, params: p.Message) -> int:
        id_ = self.next_id
        self.next_id += 1
        line = json.dumps(p.request(id_, method, params)).encode() + b"\n"
        self.child.stdin.write(line)
        await self.child.stdin.drain()
        return id_

    async def answer(self, id_: int) -> p.Incoming:
        """The response to ``id_``, skipping notifications; fails on anything malformed."""
        while True:
            line = await asyncio.wait_for(
                processes.read_line(self.child.stdout, self.limits.max_message_bytes),
                self.limits.start_timeout,
            )
            if not line:
                raise _Failed(f"the runner ended its output before answering request {id_}")
            try:
                incoming = p.parse_line(line)
            except p.ProtocolError as error:
                raise _Failed(f"it wrote a line that breaks the contract: {error}") from error
            if incoming.method is None:
                if incoming.id != id_:
                    raise _Failed(f"it answered id {incoming.id!r} while troupe waited for {id_}")
                return incoming

    async def exits(self) -> bool:
        try:
            await asyncio.wait_for(self.child.wait(), self.limits.cancel_grace)
        except TimeoutError:
            return False
        return True

    async def initialize(self, versions: list[int]) -> p.Incoming:
        host = p.Named("troupe-conformance", version("troupe"))
        return await self.answer(
            await self.send("initialize", p.InitializeParams(versions, host, []))
        )

    async def start(self, options: Mapping[str, object], workspace: Path) -> p.Incoming:
        params = p.RunStartParams(
            str(uuid.uuid4()),
            "conformance check",
            str(workspace),
            dict(options),
            p.StartLimits(self.limits.event_max_bytes),
        )
        return await self.answer(await self.send("run/start", params))


async def _with_runner(
    command: RunnerCommand, limits: RunLimits, body: Callable[[_Driver], Awaitable[None]]
) -> None:
    child = await processes.start(
        command.argv,
        cwd=command.cwd,
        env=processes.build_environment(defaults.RUNNER_ENVIRONMENT, explicit=command.env),
        line_limit=limits.max_message_bytes,
        search_path=command.search_path,
    )
    try:
        await body(_Driver(child, limits))
    finally:
        child.kill_tree()
        with contextlib.suppress(Exception):
            await asyncio.wait_for(child.wait(), limits.cancel_grace)
        child.release()


def _started(answer: p.Incoming, step: str) -> None:
    if answer.error is not None:
        raise _Failed(f"it refused {step}: {answer.error.data.problem}")


async def check_runner(
    command: RunnerCommand,
    options: Mapping[str, object],
    *,
    workspace: Path,
    limits: RunLimits | None = None,
) -> list[CheckResult]:
    """Run every conformance check against the runner ``command``."""
    limits = limits or RunLimits(run_timeout=120.0)

    async def handshake(driver: _Driver) -> None:
        answer = await driver.initialize([p.PROTOCOL_VERSION])
        _started(answer, "initialize")
        try:
            result = p.InitializeResult.from_data(answer.result)
        except p.ProtocolError as error:
            raise _Failed(f"its initialize answer breaks the contract: {error}") from error
        if result.protocol_version != p.PROTOCOL_VERSION:
            raise _Failed(f"it chose version {result.protocol_version}, which wasn't offered")
        if result.capabilities:
            raise _Failed(f"it named capabilities that weren't offered: {result.capabilities}")

    async def version_refusal(driver: _Driver) -> None:
        answer = await driver.initialize([9999])
        if answer.error is None:
            raise _Failed("it accepted protocol version 9999, which no runner supports")

    async def second_start(driver: _Driver) -> None:
        _started(await driver.initialize([p.PROTOCOL_VERSION]), "initialize")
        _started(await driver.start(options, workspace), "run/start")
        if (await driver.start(options, workspace)).error is None:
            raise _Failed("it accepted a second run/start in the same process")

    async def cancel(driver: _Driver) -> None:
        _started(await driver.initialize([p.PROTOCOL_VERSION]), "initialize")
        start = await driver.start(options, workspace)
        _started(start, "run/start")
        run_id = p.RunStartResult.from_data(start.result).run_id
        answer = await driver.answer(await driver.send("run/cancel", p.RunCancelParams(run_id)))
        if answer.error is not None:
            raise _Failed(f"it refused run/cancel: {answer.error.data.problem}")
        if not await driver.exits():
            raise _Failed(f"it didn't exit within {limits.cancel_grace:g}s of run/cancel")

    async def end_of_input(driver: _Driver) -> None:
        _started(await driver.initialize([p.PROTOCOL_VERSION]), "initialize")
        _started(await driver.start(options, workspace), "run/start")
        driver.child.close_stdin()

        async def drain_then_exit() -> None:
            while await processes.read_line(driver.child.stdout, limits.max_message_bytes):
                pass
            await driver.child.wait()

        try:
            await asyncio.wait_for(drain_then_exit(), limits.cancel_grace)
        except TimeoutError:
            raise _Failed(
                f"it didn't exit within {limits.cancel_grace:g}s of its input closing"
            ) from None

    results: list[CheckResult] = []
    checks: list[tuple[str, Callable[[_Driver], Awaitable[None]]]] = [
        ("handshake", handshake),
        ("version refusal", version_refusal),
        ("second run/start refused", second_start),
        ("cancel acknowledged, then exit", cancel),
        ("exit on end of input", end_of_input),
    ]
    for name, body in checks:
        try:
            await _with_runner(command, limits, body)
        except (_Failed, TimeoutError, OSError) as failure:
            problem = str(failure) or f"it didn't answer within {limits.start_timeout:g}s"
            results.append(CheckResult(name, False, problem))
        else:
            results.append(CheckResult(name, True))

    outcome = await run_actor(
        command,
        RunRequest(str(uuid.uuid4()), "conformance check", workspace, options),
        store=MemoryArtifactStore(),
        effect=NoEffectExpected(),
        limits=limits,
    )
    whole_run: str | None = None
    if outcome.outcome is not Outcome.SUCCEEDED:
        whole_run = f"the run ended {outcome.outcome}"
        if outcome.error is not None:
            whole_run += f": {outcome.error.problem}"
    results.append(
        CheckResult("a whole run: init first, seq, result, shutdown", whole_run is None, whole_run)
    )
    return results
