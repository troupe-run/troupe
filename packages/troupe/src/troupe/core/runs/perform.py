"""perform: run one actor, and record the run (spec: runs, stages, policy; perform-status-logs
design D4, D5, D8, D9, D11).

Everything that can refuse runs first, before a runner starts or anything is written: who is
acting, the policy, the stage's admission and the runner's name. Then perform mints the run id,
takes the run's lease, stores the instructions and options as artifacts, and runs the host. Each run
event is recorded as it arrives, through a worker thread so the event store's fsyncs and git calls
stay off the event loop, and the run's end is recorded once the host returns.

A recording failure never raises into the run host: it cancels the run, no later event is recorded
(a gap would break the seq rule), the end is still attempted with what failed, and then perform
fails with run.recording-failed.
"""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import UUID, uuid4

from troupe.core import defaults, strict_json
from troupe.core.artifacts import ArtifactStore, load_store
from troupe.core.client import messages as m
from troupe.core.client.dispatch import Send
from troupe.core.client.session import Session
from troupe.core.errors import TroupeError
from troupe.core.events import Command, EventStore
from troupe.core.files import directory_lock
from troupe.core.identity import Identity
from troupe.core.interim import runner_command
from troupe.core.notices import Notice
from troupe.core.policy import read_policy
from troupe.core.runners import protocol as p
from troupe.core.runners.effects import EffectCheck, ExpectedFiles, NoEffectExpected
from troupe.core.runners.host import RunnerCommand, RunRequest, run_actor
from troupe.core.runners.limits import RunLimits
from troupe.core.runs.aggregate import Run
from troupe.core.runs.projections import fold_runs
from troupe.core.stages import load_stage


def local_dir(theatre: Path) -> Path:
    return theatre / ".troupe" / "local"


def lease_dir(theatre: Path, run_id: str) -> Path:
    """Where a run's lease is held while its perform is alive (design D11)."""
    return local_dir(theatre) / "runs" / run_id


def open_event_store(session: Session) -> EventStore:
    return EventStore.open(
        session.theatre,
        vcs=defaults.VCS,
        store=defaults.EVENT_STORE,
        env=session.env,
        clock=session.clock,
    )


def open_artifact_store(session: Session) -> ArtifactStore:
    return load_store(defaults.ARTIFACT_STORE, local_dir(session.theatre) / "artifacts")


@dataclass(frozen=True)
class Backends:
    """Where runs are recorded and kept, and the limits they run under. Tests replace these."""

    event_store: Callable[[Session], EventStore] = open_event_store
    artifact_store: Callable[[Session], ArtifactStore] = open_artifact_store
    limits: RunLimits | None = None


def effect_check_for(check: m.EffectCheck, theatre: Path) -> EffectCheck:
    if isinstance(check, m.NoEffectCheck):
        return NoEffectExpected()
    return ExpectedFiles([theatre.joinpath(*PurePosixPath(path).parts) for path in check.paths])


def _as_troupe_error(error: BaseException) -> TroupeError:
    if isinstance(error, TroupeError):
        return error
    return TroupeError(
        "internal.unexpected",
        problem=f"troupe hit an unexpected error: {type(error).__name__}: {error}",
        fix="This is a bug in troupe. Please report it at https://github.com/troupe-run/troupe/issues",
    )


class _Recorder:
    """Records one run's events as they arrive, and its end."""

    def __init__(
        self,
        run_id: str,
        request: m.PerformRequest,
        store: EventStore,
        person: Command,
        agent: Command,
        admission: dict[str, Any],
        refs: tuple[str, str],
        send: Send,
        cancel: asyncio.Event,
    ) -> None:
        self.run_id = run_id
        self.request = request
        self.store = store
        self.stale = False
        self.person = person
        self.agent = agent
        self.admission = admission
        self.instructions_ref, self.options_ref = refs
        self.send = send
        self.cancel = cancel
        self.run: Run | None = None
        self.failure: tuple[int, TroupeError] | None = None

    def _start(self, init: p.RunEvent | None) -> Run:
        reported = None
        if isinstance(init, p.InitEvent):
            reported = {"name": init.runner.name, "version": init.runner.version}
        run = Run(
            run_id=self.run_id,
            actor=self.request.actor,
            runner_requested=self.request.runner,
            runner_reported=reported,
            stage=self.admission,
            effect_check=self.request.effect_check.to_data(),
            instructions=self.instructions_ref,
            options=self.options_ref,
        )
        self.person.record(run.collect_events())
        self.run = run
        return run

    def _record(self, event: p.RunEvent) -> str:
        run = self.run if self.run is not None else self._start(event)
        run.report(event.seq, event.to_data())
        [recorded] = self.agent.record(run.collect_events())
        return recorded.at

    async def on_event(self, event: p.RunEvent) -> None:
        if self.failure is not None:
            return
        try:
            at = await asyncio.to_thread(self._record, event)
        except Exception as error:  # any failure to record stops the run
            # The aggregate may have counted what wasn't recorded; the end reloads it (_end).
            self.stale = True
            self.failure = (event.seq, _as_troupe_error(error))
            self.cancel.set()
            return
        self.send(
            m.LoggedEvent.from_data(
                {
                    "kind": "event",
                    "runId": self.run_id,
                    "seq": event.seq,
                    "at": at,
                    "event": event.to_data(),
                }
            )
        )

    def _end(self, outcome: dict[str, Any]) -> None:
        if self.stale and self.run is not None:
            loaded = self.store.load(UUID(self.run_id))
            if not isinstance(loaded, Run):
                raise TypeError(f"run {self.run_id}'s stream doesn't hold a run")
            self.run = loaded
        run = self.run if self.run is not None else self._start(None)
        recording = None
        if self.failure is not None:
            recording = {"failedAt": self.failure[0], "error": self.failure[1].to_data()}
        run.end(outcome, recording)
        self.agent.record(run.collect_events())

    async def end(self, outcome: dict[str, Any]) -> None:
        await asyncio.to_thread(self._end, outcome)


async def perform(
    request: m.PerformRequest, session: Session, send: Send, *, backends: Backends | None = None
) -> m.PerformResult:
    """Run the actor ``request`` names and record the run; the result is the recorded run."""
    backends = backends or Backends()
    theatre = session.theatre
    store = await asyncio.to_thread(backends.event_store, session)
    person_identity = await asyncio.to_thread(store.identify)
    stage = load_stage(defaults.STAGE)
    admission = stage.admit(read_policy(session.env))
    argv = runner_command(request.runner)

    run_id = str(uuid4())
    lease = lease_dir(theatre, run_id)
    lease.mkdir(parents=True)
    with directory_lock(lease):
        send(m.Started(run_id=run_id))
        artifacts = backends.artifact_store(session)
        instructions = request.instructions or ""
        options: dict[str, object] = request.options or {}
        refs = (
            artifacts.put(instructions.encode("utf-8")),
            artifacts.put(strict_json.dumps(options).encode("utf-8")),
        )
        person = store.command(via="cli", actor=person_identity, stage=admission)
        agent = person.acting_as(
            Identity(kind="agent", id=request.actor, source="troupe"), via="runner"
        )
        cancel = session.cancel.bind()
        recorder = _Recorder(
            run_id, request, store, person, agent, admission.to_data(), refs, send, cancel
        )
        workspace = stage.workspace(theatre)
        outcome = await run_actor(
            RunnerCommand(list(argv), cwd=workspace),
            RunRequest(run_id, instructions, workspace, options),
            store=artifacts,
            effect=effect_check_for(request.effect_check, theatre),
            limits=backends.limits,
            on_event=recorder.on_event,
            on_announce=lambda notice: send(_notice(notice)),
            cancel=cancel,
        )
        data = outcome.to_data()
        del data["runId"]
        try:
            await recorder.end(data)
        except Exception as error:
            raise _recording_failed(
                run_id, recorder.failure, outcome.transcript, ended=_as_troupe_error(error)
            ) from error
        if recorder.failure is not None:
            raise _recording_failed(run_id, recorder.failure, outcome.transcript, ended=None)
        history = await asyncio.to_thread(store.history, UUID(run_id))
    [view] = fold_runs(history).values()
    return m.PerformResult(run=view.summary("ended"))


def _recording_failed(
    run_id: str,
    failure: tuple[int, TroupeError] | None,
    transcript: str | None,
    *,
    ended: TroupeError | None,
) -> TroupeError:
    first = failure[1] if failure is not None else ended
    if first is None:
        raise ValueError("a recording failure needs something that failed")
    where = f"from run event {failure[0]} on" if failure is not None else "for the run's end"
    end = (
        "Its end couldn't be recorded either, so status shows it as interrupted."
        if ended is not None
        else "Its end was recorded, saying where recording stopped."
    )
    return TroupeError(
        "run.recording-failed",
        problem=f"Run {run_id} couldn't be recorded {where}: {first.problem} The run was "
        f"stopped. {end}",
        fix=f"{first.fix} The run's transcript is kept as {transcript or 'nothing'}.",
        details={
            "run": run_id,
            "failedAt": None if failure is None else failure[0],
            "error": first.to_data(),
            "endError": None if ended is None else ended.to_data(),
            "transcript": transcript,
        },
    )


def _notice(notice: Notice) -> m.NoticeUpdate:
    return m.NoticeUpdate(notice=m.NoticeData.of(notice))
