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
import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import UUID, uuid4

from troupe.core import defaults
from troupe.core.artifacts import ArtifactStore
from troupe.core.client import messages as m
from troupe.core.client.dispatch import Send
from troupe.core.client.session import Session
from troupe.core.config.commands import sync_files
from troupe.core.config.merge import Merged
from troupe.core.config.projection import plan, refuse, render
from troupe.core.config.stream import read, refuse_conflicts
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
from troupe.core.stores import local_dir, open_artifact_store, open_event_store


def lease_dir(theatre: Path, run_id: str) -> Path:
    """Where a run's lease is held while its perform is alive (design D11)."""
    return local_dir(theatre) / "runs" / run_id


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


@dataclass(frozen=True)
class _What:
    """What a perform runs, as config defines the actor (config-model design D14)."""

    actor: str
    runner: str
    options: dict[str, object]
    effect_check: m.EffectCheck
    character: str | None
    config: tuple[str, ...]


def _from_config(merged: Merged, name: str) -> _What:
    """The actor ``name`` as config defines it. Refused when config has no such actor."""
    actors = merged.config.get("actors", {})
    actor = actors.get(name) if isinstance(actors, dict) else None
    if not isinstance(actor, dict):
        known = sorted(actors) if isinstance(actors, dict) else []
        listed = ", ".join(known) or "none yet"
        raise TroupeError(
            "config.unknown-actor",
            problem=f"Config has no actor named {name!r} (it has: {listed}).",
            fix=f"Perform one of the actors config has, or define {name} with troupe config set "
            f"actors.{name}.runner=... actors.{name}.expect=...",
            details={"actor": name, "known": known},
        )
    paths = list(dict.fromkeys(actor["expect"]))
    check: m.EffectCheck = m.FilesEffectCheck(paths=paths) if paths else m.NoEffectCheck()
    character = actor.get("character")
    return _What(
        actor=name,
        runner=str(actor["runner"]),
        options=dict(actor.get("options", {})),
        effect_check=check,
        character=character if isinstance(character, str) else None,
        config=merged.heads,
    )


def _summary(text: str | None) -> m.TextSummary | None:
    if not text:
        return None
    digest = "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()
    return m.TextSummary(hash=digest, length=len(text))


class _Recorder:
    """Records one run's events as they arrive, and its end."""

    def __init__(
        self,
        run_id: str,
        what: "_What",
        store: EventStore,
        person: Command,
        agent: Command,
        admission: dict[str, Any],
        direction_ref: str,
        send: Send,
        cancel: asyncio.Event,
    ) -> None:
        self.run_id = run_id
        self.what = what
        self.store = store
        self.stale = False
        self.person = person
        self.agent = agent
        self.admission = admission
        self.direction_ref = direction_ref
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
            actor=self.what.actor,
            runner_requested=self.what.runner,
            runner_reported=reported,
            stage=self.admission,
            effect_check=self.what.effect_check.to_data(),
            direction=self.direction_ref,
            config=list(self.what.config),
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
    merged = await asyncio.to_thread(read, store)
    refuse_conflicts(merged)
    what = _from_config(merged, request.actor)
    argv = runner_command(what.runner)
    direction = request.direction or ""
    if request.rehearse:
        # Every check a flush makes, without writing: a rehearsal changes nothing.
        refuse(plan(theatre / ".troupe", render(merged.config), merged.files))
        return m.PerformResult(
            rehearsal=m.Rehearsal(
                actor=what.actor,
                runner=what.runner,
                stage=m.StageData.from_data(admission.to_data()),
                effect_check=what.effect_check,
                config=list(what.config),
                character=_summary(what.character),
                direction=_summary(direction),
            )
        )
    for notice in await asyncio.to_thread(sync_files, session, store, merged, send):
        send(_notice(notice))

    run_id = str(uuid4())
    lease = lease_dir(theatre, run_id)
    lease.mkdir(parents=True)
    with directory_lock(lease):
        send(m.Started(run_id=run_id))
        artifacts = backends.artifact_store(session)
        direction_ref = artifacts.put(direction.encode("utf-8"))
        person = store.command(via="cli", actor=person_identity, stage=admission)
        agent = person.acting_as(
            Identity(kind="agent", id=what.actor, source="troupe"), via="runner"
        )
        cancel = session.cancel.bind()
        recorder = _Recorder(
            run_id, what, store, person, agent, admission.to_data(), direction_ref, send, cancel
        )
        workspace = stage.workspace(theatre)
        outcome = await run_actor(
            RunnerCommand(list(argv), cwd=workspace),
            RunRequest(run_id, direction, workspace, what.options, character=what.character),
            store=artifacts,
            effect=effect_check_for(what.effect_check, theatre),
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
        details=_recording_details(run_id, failure, first, transcript, ended=ended),
    )


def _recording_details(
    run_id: str,
    failure: tuple[int, TroupeError] | None,
    first: TroupeError,
    transcript: str | None,
    *,
    ended: TroupeError | None,
) -> dict[str, object]:
    """run.recording-failed's details, leaving out what it can't name: no seq when only the end
    failed, no end error when the end was recorded, no transcript when the runner never started."""
    details: dict[str, object] = {"run": run_id, "error": first.to_data()}
    if failure is not None:
        details["failedAt"] = failure[0]
    if ended is not None:
        details["endError"] = ended.to_data()
    if transcript is not None:
        details["transcript"] = transcript
    return details


def _notice(notice: Notice) -> m.NoticeUpdate:
    return m.NoticeUpdate(notice=m.NoticeData.of(notice))
