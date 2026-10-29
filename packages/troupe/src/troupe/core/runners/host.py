"""The run host: runs an actor through an out-of-process runner (spec: actor-runners; design D7).

``run_actor`` starts the runner under the runner environment policy, performs the handshake, starts
the run, and supervises it: every message is checked against the contract (design D1a), events go
to the caller in order as they arrive, the transcript and standard error are streamed into the
artifact store, silences and retries are announced as notices, and every limit is enforced. It
always returns one RunOutcome, derived by troupe.core.runners.outcome; a failed run is not raised.
"""

import asyncio
import base64
import binascii
import contextlib
import json
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from importlib.metadata import version
from pathlib import Path
from typing import Any

from troupe.core import defaults
from troupe.core.artifacts import ArtifactStore, ArtifactWriter
from troupe.core.errors import TroupeError
from troupe.core.notices import Notice
from troupe.core.runners import protocol as p
from troupe.core.runners.effects import EffectCheck, EffectVerdict
from troupe.core.runners.limits import RunLimits
from troupe.core.runners.outcome import (
    Ending,
    RunFacts,
    RunOutcome,
    StopReason,
    derive_outcome,
)
from troupe.platform import processes
from troupe.platform.errors import CommandNotFoundError, LineTooLongError

EventCallback = Callable[[p.RunEvent], Awaitable[None]]
"""Receives each run event (or the oversized event standing in for one), in seq order."""

AnnounceCallback = Callable[[Notice], None]
"""Receives each notice: a long silence, a retry."""

MessageCallback = Callable[[str, Mapping[str, Any]], None]
"""Receives ("sent" or "received", message) for every protocol message, for tracing and tests."""

OFFERED_CAPABILITIES: tuple[str, ...] = ()
"""The capabilities this troupe offers runners. Version 0 defines none."""

_POLL_SECONDS = 0.05
_FIX_RUNNER_BUG = (
    "This is a fault in the runner. Report it to the runner's author, with the run's transcript "
    "and standard error."
)


@dataclass(frozen=True)
class RunnerCommand:
    """How to start a runner: its command line, and the variables it is given explicitly."""

    argv: Sequence[str]
    cwd: Path
    env: Mapping[str, str] = field(default_factory=dict)
    search_path: str | None = None


@dataclass(frozen=True)
class RunRequest:
    run_id: str
    direction: str
    workspace: Path
    options: Mapping[str, object] = field(default_factory=dict)
    character: str | None = None
    """Who the actor is, sent apart from the direction; None when it has no character."""


class _Violation(Exception):  # noqa: N818 - it carries the protocol error, not a Python failure
    def __init__(self, error: TroupeError) -> None:
        super().__init__(error.problem)
        self.error = error


def _violation(problem: str, line: int | None = None, **details: object) -> _Violation:
    where = f" (line {line} of its output)" if line is not None else ""
    return _Violation(
        TroupeError(
            "runner.protocol",
            problem=f"The runner broke the runner contract{where}: {problem}",
            fix=_FIX_RUNNER_BUG,
            details={"line": line, **details} if line is not None else dict(details),
        )
    )


class _StderrSink:
    """Keeps a runner's standard error within its limit: the first half as it comes, the last half
    in a rolling buffer, and a marker saying how much was left out between them."""

    def __init__(self, writer: ArtifactWriter, limit: int) -> None:
        self._writer = writer
        self._head_limit = limit // 2
        self._tail_limit = limit - self._head_limit
        self._head_written = 0
        self._tail = bytearray()
        self.total = 0

    def add(self, data: bytes) -> None:
        self.total += len(data)
        take = min(len(data), self._head_limit - self._head_written)
        if take:
            self._writer.write(data[:take])
            self._head_written += take
        self._tail.extend(data[take:])
        del self._tail[: max(0, len(self._tail) - self._tail_limit)]

    def finish(self) -> str:
        left_out = self.total - self._head_written - len(self._tail)
        if left_out:
            self._writer.write(
                f"\n[troupe: {left_out} bytes of standard error left out]\n".encode()
            )
        self._writer.write(bytes(self._tail))
        return self._writer.finish()


class _Run:
    """The state of one run while it is supervised."""

    def __init__(
        self,
        command: RunnerCommand,
        request: RunRequest,
        store: ArtifactStore,
        effect: EffectCheck,
        limits: RunLimits,
        on_event: EventCallback | None,
        on_announce: AnnounceCallback | None,
        on_message: MessageCallback | None,
        cancel: asyncio.Event | None,
    ) -> None:
        self.command = command
        self.request = request
        self.store = store
        self.effect = effect
        self.limits = limits
        self.on_event = on_event
        self.on_announce = on_announce
        self.on_message = on_message
        self.cancel = cancel or asyncio.Event()
        self.child: processes.ChildProcess | None = None
        self.transcript: ArtifactWriter | None = None
        self.transcript_bytes = 0
        self.stderr: _StderrSink | None = None
        self.line_number = 0
        self.next_id = 1
        self.pending: dict[int, str] = {}
        self.responses: dict[int, asyncio.Future[p.Incoming]] = {}
        self.next_seq = 0
        self.tool_calls: set[str] = set()
        self.result: p.ResultEvent | None = None
        self.violation: TroupeError | None = None
        self.stop: StopReason | None = None
        self.stopping = False
        self.last_event = time.monotonic()
        self.silence_announced = False

    # Writing to the runner

    async def send(self, method: str, params: p.Message) -> int:
        id_ = self.next_id
        self.next_id += 1
        message = p.request(id_, method, params)
        self.pending[id_] = method
        self.responses[id_] = asyncio.get_running_loop().create_future()
        if self.on_message is not None:
            self.on_message("sent", message)
        child = self._child()
        with contextlib.suppress(ConnectionError, RuntimeError, OSError):
            child.stdin.write(json.dumps(message, separators=(",", ":")).encode() + b"\n")
            await child.stdin.drain()
        return id_

    def _child(self) -> processes.ChildProcess:
        if self.child is None:
            raise RuntimeError("the runner hasn't started")
        return self.child

    # Reading from the runner

    async def read(self) -> p.Incoming | None:
        """The next message from the runner, or None at end of output."""
        try:
            line = await processes.read_line(self._child().stdout, self.limits.max_message_bytes)
        except LineTooLongError as error:
            raise _violation(
                f"a message was longer than the limit of {error.limit} bytes",
                self.line_number + 1,
                limitBytes=error.limit,
            ) from error
        if not line:
            return None
        self.line_number += 1
        try:
            incoming = p.parse_line(line)
        except p.ProtocolError as error:
            raise _violation(str(error), self.line_number) from error
        if self.on_message is not None:
            self.on_message("received", json.loads(line))
        if incoming.method is not None:
            await self.notification(incoming, line)
        else:
            self.response(incoming)
        return incoming

    def response(self, incoming: p.Incoming) -> None:
        if not isinstance(incoming.id, int) or incoming.id not in self.pending:
            raise _violation(
                f"it answered a request troupe never sent (id {incoming.id!r})", self.line_number
            )
        del self.pending[incoming.id]
        self.responses[incoming.id].set_result(incoming)

    async def notification(self, incoming: p.Incoming, line: bytes) -> None:
        if incoming.method == "run/event":
            await self.event(incoming.params, line)
        elif incoming.method == "run/transcript":
            self.transcript_record(incoming.params)
        else:
            raise _violation(
                f"it sent a notification the contract doesn't define ({incoming.method!r})",
                self.line_number,
            )

    async def event(self, params: object, line: bytes) -> None:
        try:
            event = p.parse_event(params)
        except p.ProtocolError as error:
            raise _violation(str(error), self.line_number) from error
        if event.run_id != self.request.run_id:
            raise _violation(
                f"it sent an event for run {event.run_id}, not this run", self.line_number
            )
        if self.result is not None:
            raise _violation("it sent an event after its result event", self.line_number)
        if event.seq != self.next_seq:
            raise _violation(
                f"event seq {event.seq} should have been {self.next_seq}", self.line_number
            )
        if self.next_seq == 0 and not isinstance(event, p.InitEvent):
            raise _violation(f"its first event was {event.TYPE!r}, not 'init'", self.line_number)
        if isinstance(event, p.ToolCallEvent):
            self.tool_calls.add(event.call_id)
        if isinstance(event, p.ToolResultEvent) and event.call_id not in self.tool_calls:
            raise _violation(
                f"a tool_result named call {event.call_id!r}, which no earlier tool_call did",
                self.line_number,
            )
        self.next_seq += 1
        self.last_event = time.monotonic()
        self.silence_announced = False
        if isinstance(event, p.ResultEvent):
            self.result = event
        passed_on: p.RunEvent = event
        size = len(json.dumps(params, ensure_ascii=False, separators=(",", ":")).encode())
        if size > self.limits.event_max_bytes:
            ref = self.store.put(line.rstrip(b"\r\n"))
            passed_on = p.OversizedEvent(event.run_id, event.seq, event.TYPE, size, ref)  # type: ignore[arg-type]
        if self.on_event is not None:
            await self.on_event(passed_on)
        if isinstance(event, p.RetryEvent):
            self.announce_retry(event)
            if event.reason == "authentication" and self.limits.fail_fast_on_auth_retry:
                await self.request_stop(StopReason.AUTHENTICATION)

    def transcript_record(self, params: object) -> None:
        try:
            record = p.TranscriptRecord.from_data(params)
        except p.ProtocolError as error:
            raise _violation(str(error), self.line_number) from error
        if record.run_id != self.request.run_id:
            raise _violation(
                f"it sent a transcript record for run {record.run_id}, not this run",
                self.line_number,
            )
        if record.encoding == "base64":
            try:
                data = base64.b64decode(record.record, validate=True)
            except (binascii.Error, ValueError) as error:
                raise _violation(
                    "a base64 transcript record isn't valid base64", self.line_number
                ) from error
        else:
            data = record.record.encode()
        if self.transcript is None:
            raise RuntimeError("the transcript writer isn't open")
        self.transcript.write(data + b"\n")
        self.transcript_bytes += len(data) + 1
        if self.transcript_bytes > self.limits.transcript_max_bytes and not self.stopping:
            asyncio.get_running_loop().create_task(self.request_stop(StopReason.TRANSCRIPT_LIMIT))

    # Notices

    def notice(self, notice: Notice) -> None:
        if self.on_announce is not None:
            self.on_announce(notice)

    def announce_retry(self, event: p.RetryEvent) -> None:
        of = f" of {event.max_attempts}" if event.max_attempts is not None else ""
        details: dict[str, object] = {
            "attempt": event.attempt,
            "delayMs": event.delay_ms,
            "reason": event.reason,
        }
        if event.max_attempts is not None:
            details["maxAttempts"] = event.max_attempts
        self.notice(
            Notice(
                "run.retrying",
                problem=f"The runner's engine is retrying (attempt {event.attempt}{of}, reason: "
                f"{event.reason}), next in {event.delay_ms / 1000:g}s.",
                fix="Wait; troupe stops the run at its limits. Check the credential if the reason "
                "is authentication.",
                details=details,
            )
        )

    # Stopping

    async def request_stop(self, reason: StopReason) -> None:
        """Ask the runner to stop: run/cancel, then a kill after the grace period."""
        if self.stopping:
            return
        self.stopping = True
        self.stop = reason
        await self.send("run/cancel", p.RunCancelParams(self.request.run_id))
        asyncio.get_running_loop().create_task(self.kill_after_grace())

    async def kill_after_grace(self) -> None:
        child = self._child()
        try:
            await asyncio.wait_for(child.wait(), self.limits.cancel_grace)
        except TimeoutError:
            self.kill()

    def kill(self) -> None:
        child = self._child()
        # Only for pid reuse: once asyncio has reaped the runner, its process group id may belong to
        # another group. Whether the run ends killed is decided from the exit status, not from here.
        if child.returncode is None:
            child.kill_tree()

    async def watchdog(self, started: float) -> None:
        while True:
            await asyncio.sleep(_POLL_SECONDS)
            now = time.monotonic()
            if self.result is not None:
                return
            if self.cancel.is_set():
                await self.request_stop(StopReason.CALLER)
            if now - started >= self.limits.run_timeout:
                await self.request_stop(StopReason.RUN_TIMEOUT)
            silent = now - self.last_event
            if not self.silence_announced and silent >= self.limits.silence_announce:
                self.silence_announced = True
                self.notice(
                    Notice(
                        "run.silent",
                        problem=f"The run has sent no event for {silent:.0f}s.",
                        fix="Wait, or cancel the run if it seems stuck. troupe stops it at its "
                        "time limit.",
                        details={"seconds": round(silent, 1)},
                    )
                )

    async def drain_stderr(self) -> None:
        stream = self._child().stderr
        while chunk := await stream.read(64 * 1024):
            if self.stderr is not None:
                self.stderr.add(chunk)


def _start_error(code: str, problem: str, fix: str, **details: object) -> TroupeError:
    return TroupeError(code, problem=problem, fix=fix, details=dict(details))


async def run_actor(
    command: RunnerCommand,
    request: RunRequest,
    *,
    store: ArtifactStore,
    effect: EffectCheck,
    limits: RunLimits | None = None,
    on_event: EventCallback | None = None,
    on_announce: AnnounceCallback | None = None,
    on_message: MessageCallback | None = None,
    cancel: asyncio.Event | None = None,
) -> RunOutcome:
    """Run one actor through a runner and return the run's one outcome.

    Set ``cancel`` to cancel the run. The effect check has no default: a run with nothing to check
    passes NoEffectExpected.
    """
    if not p.RUN_ID_PATTERN.match(request.run_id):
        raise ValueError(f"run id {request.run_id!r} isn't a canonical lowercase UUID")
    limits = limits or RunLimits()
    run = _Run(command, request, store, effect, limits, on_event, on_announce, on_message, cancel)
    effect.before()
    try:
        run.child = await processes.start(
            command.argv,
            cwd=command.cwd,
            env=processes.build_environment(defaults.RUNNER_ENVIRONMENT, explicit=command.env),
            line_limit=limits.max_message_bytes,
            search_path=command.search_path,
        )
    except (CommandNotFoundError, OSError) as error:
        name = command.argv[0] if command.argv else ""
        reason = "it wasn't found" if isinstance(error, CommandNotFoundError) else str(error)
        return not_started(
            request.run_id,
            limits,
            _start_error(
                "runner.start-failed",
                f"Couldn't start the runner {name!r}: {reason}.",
                "Check that the runner is installed and that its command is right.",
                command=name,
            ),
        )
    run.transcript = store.open_writer()
    run.stderr = _StderrSink(store.open_writer(), limits.stderr_max_bytes)
    stderr_task = asyncio.get_running_loop().create_task(run.drain_stderr())
    start_error: TroupeError | None = None
    try:
        start_error = await asyncio.wait_for(_start(run), limits.start_timeout)
        if start_error is None:
            await _supervise(run)
    except TimeoutError:
        start_error = _start_error(
            "runner.start-timeout",
            f"The runner didn't answer the handshake within {limits.start_timeout:g}s.",
            "Check the runner starts and reads its standard input; raise "
            "RUNNER_START_TIMEOUT_SECONDS if it is just slow to start.",
            limitSeconds=limits.start_timeout,
        )
    except _Violation as violation:
        run.violation = violation.error
    finally:
        exit_code = await _finish_process(
            run, stop_now=start_error is not None or run.violation is not None
        )
        with contextlib.suppress(Exception):
            await asyncio.wait_for(stderr_task, limits.cancel_grace)
        stderr_task.cancel()
        transcript_ref = run.transcript.finish()
        stderr_ref = run.stderr.finish()
        run._child().release()
    ending = Ending.KILLED if run._child().ended_by_kill(exit_code) else Ending.EXITED
    verdict: EffectVerdict | None = None
    if run.result is not None and run.result.status == "ok" and start_error is None:
        verdict = effect.after()
    outcome, outcome_error = derive_outcome(
        RunFacts(
            limits=limits,
            ending=ending,
            exit_code=exit_code,
            start_error=start_error,
            violation=run.violation,
            stop=run.stop,
            result=run.result if start_error is None else None,
            effect=verdict,
        )
    )
    return RunOutcome(
        request.run_id,
        outcome,
        outcome_error,
        run.result,
        exit_code,
        ending,
        transcript_ref,
        stderr_ref,
        limits,
    )


def not_started(run_id: str, limits: RunLimits | None, error: TroupeError) -> RunOutcome:
    """The outcome of a run whose runner never started because of ``error``: could-not-start.
    perform uses it, too, for a run that failed before its runner was started."""
    limits = limits or RunLimits()
    outcome, error_out = derive_outcome(
        RunFacts(limits=limits, ending=Ending.NEVER_STARTED, start_error=error)
    )
    return RunOutcome(
        run_id, outcome, error_out, None, None, Ending.NEVER_STARTED, None, None, limits
    )


async def _await_response(run: _Run, id_: int) -> p.Incoming | None:
    """Read until the response to ``id_`` arrives; None if the runner ended its output first."""
    future = run.responses[id_]
    while not future.done():
        if await run.read() is None:
            return None
    return future.result()


async def _start(run: _Run) -> TroupeError | None:
    """The handshake and run/start. Returns the error that kept the run from starting, if any."""
    host = p.Named("troupe", version("troupe"))
    id_ = await run.send(
        "initialize", p.InitializeParams([p.PROTOCOL_VERSION], host, list(OFFERED_CAPABILITIES))
    )
    answer = await _await_response(run, id_)
    if answer is None:
        return _start_error(
            "runner.start-failed",
            "The runner ended before answering the handshake.",
            "Check the runner's standard error for why it stopped.",
        )
    if answer.error is not None:
        data = answer.error.data
        code = (
            "runner.incompatible"
            if data.code == "runner.unsupported-version"
            else ("runner.start-failed")
        )
        return _start_error(
            code,
            f"The runner refused the handshake: {data.problem}",
            data.fix,
            runnerError=data.to_data(),
        )
    try:
        result = p.InitializeResult.from_data(answer.result)
    except p.ProtocolError as error:
        raise _violation(str(error), run.line_number) from error
    if result.protocol_version != p.PROTOCOL_VERSION:
        raise _violation(
            f"it chose protocol version {result.protocol_version}, which troupe didn't offer",
            run.line_number,
        )
    unoffered = sorted(set(result.capabilities) - set(OFFERED_CAPABILITIES))
    if unoffered:
        raise _violation(
            f"it named capabilities troupe didn't offer ({', '.join(unoffered)})", run.line_number
        )
    id_ = await run.send(
        "run/start",
        p.RunStartParams(
            run_id=run.request.run_id,
            direction=run.request.direction,
            workspace=str(run.request.workspace),
            options=dict(run.request.options),
            limits=p.StartLimits(run.limits.event_max_bytes),
            character=run.request.character,
        ),
    )
    answer = await _await_response(run, id_)
    if answer is None:
        return _start_error(
            "runner.start-failed",
            "The runner ended before answering run/start.",
            "Check the runner's standard error for why it stopped.",
        )
    if answer.error is not None:
        data = answer.error.data
        return _start_error(
            "runner.start-failed",
            f"The runner refused the run: {data.problem}",
            data.fix,
            runnerError=data.to_data(),
        )
    try:
        started = p.RunStartResult.from_data(answer.result)
    except p.ProtocolError as error:
        raise _violation(str(error), run.line_number) from error
    if started.run_id != run.request.run_id:
        raise _violation(
            f"it answered run/start for run {started.run_id}, not this run", run.line_number
        )
    return None


async def _supervise(run: _Run) -> None:
    """Read the run until the runner ends its output, sending shutdown after the result."""
    watchdog = asyncio.get_running_loop().create_task(run.watchdog(time.monotonic()))
    shutdown_sent = False
    try:
        while True:
            if run.result is not None and not shutdown_sent and not run.stopping:
                shutdown_sent = True
                run.stopping = True
                await run.send("shutdown", p.Empty())
                asyncio.get_running_loop().create_task(run.kill_after_grace())
            if await run.read() is None:
                return
    finally:
        watchdog.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await watchdog


async def _finish_process(run: _Run, *, stop_now: bool) -> int:
    """Make sure the runner has ended, at once after a violation or a failed start, otherwise
    within the grace period of its output ending, and return its exit code. A runner that started
    always has one: this only returns once the process has been waited for."""
    child = run._child()
    if stop_now:
        run.kill()
    child.close_stdin()
    try:
        return await asyncio.wait_for(child.wait(), run.limits.cancel_grace)
    except TimeoutError:
        run.kill()
        return await child.wait()
