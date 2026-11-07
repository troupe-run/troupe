"""perform: run one actor, and record the run (spec: runs, stages, policy, run-workspaces;
perform-status-logs design D4, D5, D8, D9, D11; worktree-stage design D8; account-for-every-worktree
design D1, D2, D5).

Everything that can refuse runs first, before a runner starts or anything is written: who is
acting, the policy, the stage's admission, the runner's name, and, for a worktree run, whether the
theatre can have one. Then perform mints the run id, takes the run's lease, stores the direction
as an artifact, plans the run's worktree, and records the run's start, so from here on an event
names the run, and its worktree, before any part of the worktree exists: however perform stops,
status shows the run and discard can clear it. Then it makes the worktree and records that, and
runs the host in the workspace. A failure between the start and the runner ends the run
could-not-start, then fails perform with that error. When the host returns, a worktree run's
changes are captured into the artifact store, with what changed in the repository's shared state,
and recorded in the run's end. Each run event is recorded as it arrives, through a worker thread
so the event store's fsyncs and git calls stay off the event loop, and the run's end is recorded
once the host returns.

A recording failure never raises into the run host: it cancels the run, no later event is recorded
(a gap would break the seq rule), the end is still attempted with what failed, and then perform
fails with run.recording-failed.
"""

import asyncio
import hashlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import UUID, uuid4

from troupe.core import defaults, runtimes
from troupe.core.artifacts import ArtifactStore
from troupe.core.client import messages as m
from troupe.core.client.dispatch import Send
from troupe.core.client.session import Session
from troupe.core.config.commands import sync_files
from troupe.core.config.kinds import check_actor
from troupe.core.config.merge import Merged
from troupe.core.config.projection import merges, plan, refuse, render
from troupe.core.config.stream import read, refuse_conflicts
from troupe.core.config_paths import shown
from troupe.core.errors import TroupeError
from troupe.core.events import Command, EventStore
from troupe.core.files import directory_lock
from troupe.core.identity import Identity
from troupe.core.interim import runner_command, runner_environment
from troupe.core.notices import Notice
from troupe.core.policy import read_policy
from troupe.core.runners.effects import (
    DeclaredEffects,
    EffectCheck,
    ExpectedFiles,
    NoEffectExpected,
)
from troupe.core.runners.host import RunnerCommand, RunRequest, not_started, run_actor
from troupe.core.runners.limits import RunLimits
from troupe.core.runners.outcome import RunOutcome
from troupe.core.runs.aggregate import Run
from troupe.core.runs.projections import fold_runs
from troupe.core.runtimes import RunRuntime
from troupe.core.stages import load_stage
from troupe.core.stores import local_dir, open_artifact_store, open_event_store
from troupe.core.vcs import SharedState, Vcs
from troupe.core.workspaces import (
    Kind,
    Planned,
    Worktree,
    capture,
    make_worktree,
    plan_worktree,
    shared_changed,
    snapshot,
    worktree_base,
)
from troupe_plugin_sdk import runner as p
from troupe_plugin_sdk.credential import CREDENTIAL_VARIABLE
from troupe_plugin_sdk.effects import Effects


def lease_dir(theatre: Path, run_id: str) -> Path:
    """Where a run's lease is held while its perform is alive (design D11)."""
    return local_dir(theatre) / "runs" / run_id


@dataclass(frozen=True)
class Backends:
    """Where runs are recorded and kept, and the limits they run under. Tests replace these."""

    event_store: Callable[[Session], EventStore] = open_event_store
    artifact_store: Callable[[Session], ArtifactStore] = open_artifact_store
    limits: RunLimits | None = None


def expected_files_for(what: "_What", workspace: Path) -> EffectCheck:
    """The run's expected files, read in its workspace: checked only for an ok result."""
    check = what.effect_check
    if isinstance(check, m.NoEffectCheck):
        return NoEffectExpected()
    return ExpectedFiles([workspace.joinpath(*PurePosixPath(path).parts) for path in check.paths])


def audit_for(
    what: "_What", workspace: Path, vcs: Vcs, baseline: str | None = None
) -> DeclaredEffects:
    """The audit of every change the run makes in its workspace against its declared effects,
    whatever its outcome (spec: effects; declared-effects design D3, D4; failed-run-audit design
    D1). A worktree run's changes are measured from its baseline, a run in the theatre's from the
    theatre as it was when the run started."""
    declared = what.effects
    effects = Effects(
        write=tuple(declared.write), delete=tuple(declared.delete), move=tuple(declared.move)
    )

    def now() -> Mapping[str, str]:
        return vcs.file_states(workspace)

    def start() -> Mapping[str, str]:
        return vcs.file_states(workspace, at=baseline) if baseline is not None else now()

    return DeclaredEffects(what.actor, effects, start, now, in_theatre=baseline is None)


def refuse_scratch_in_theatre(root: Path, theatre: Path) -> Path:
    """``root``, where runs' scratch directories are made, unless it's inside the theatre, which
    is refused before anything is recorded (spec: effects, "Every run gets scratch space outside
    its declaration")."""
    resolved, inside = root.resolve(), theatre.resolve()
    # A theatre inside the root is fine: each run's directory is a new one made in the root.
    if resolved.is_relative_to(inside):
        raise TroupeError(
            "run.scratch-in-theatre",
            problem=f"Runs' scratch directories would be made in {root}, which is inside the "
            f"theatre {theatre}, so what a run writes there would be among your files.",
            fix="Set RUN_SCRATCH_ROOT to a directory outside the theatre, or leave it unset to "
            "use the platform's temporary directory.",
            details={"scratchRoot": str(root)},
        )
    return resolved


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
    workspace: Kind
    effects: p.EffectsDeclaration = p.READ_ONLY_DECLARATION
    runtime: str | None = None
    model: str | None = None


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
            f"{shown(('actors', name, 'runner'))}=... {shown(('actors', name, 'expect'))}=...",
            details={"actor": name, "known": known},
        )
    paths = list(dict.fromkeys(actor["expect"]))
    check: m.EffectCheck = m.FilesEffectCheck(paths=paths) if paths else m.NoEffectCheck()
    character = actor.get("character")
    workspace = actor.get("workspace", defaults.WORKSPACE)
    declared = actor.get("effects") or {}
    effects = p.EffectsDeclaration(
        write=list(declared.get("write") or []),
        delete=list(declared.get("delete") or []),
        move=list(declared.get("move") or []),
    )
    return _What(
        actor=name,
        runner=str(actor["runner"]),
        options=dict(actor.get("options", {})),
        effect_check=check,
        character=character if isinstance(character, str) else None,
        config=merged.heads,
        workspace="theatre" if workspace == "theatre" else "worktree",
        effects=effects,
        runtime=actor.get("runtime"),
        model=actor.get("model"),
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
        workspace: dict[str, Any],
        send: Send,
        cancel: asyncio.Event,
        runtime: RunRuntime | None = None,
    ) -> None:
        self.run_id = run_id
        self.what = what
        self.runtime = runtime
        self.store = store
        self.stale = False
        self.person = person
        self.agent = agent
        self.admission = admission
        self.direction_ref = direction_ref
        self.workspace = workspace
        self.send = send
        self.cancel = cancel
        self.run: Run | None = None
        self.failure: tuple[int, TroupeError] | None = None

    def _start(self) -> None:
        run = Run(
            run_id=self.run_id,
            actor=self.what.actor,
            runner_requested=self.what.runner,
            stage=self.admission,
            effect_check=self.what.effect_check.to_data(),
            direction=self.direction_ref,
            config=list(self.what.config),
            workspace=self.workspace,
            runtime=self.runtime.to_data() if self.runtime is not None else None,
        )
        self.person.record(run.collect_events())
        self.run = run

    async def start(self) -> None:
        """Record the run's start, before its workspace is made and its runner starts."""
        await asyncio.to_thread(self._start)

    def _made(self, clones: tuple[str, ...]) -> None:
        run = self._run()
        run.made_worktree(list(clones))
        self.person.record(run.collect_events())

    async def made(self, worktree: Worktree) -> None:
        """Record that the run's worktree is made, with its clone mechanisms."""
        try:
            await asyncio.to_thread(self._made, worktree.clones)
        except Exception:
            # The aggregate may have counted what wasn't recorded; the end reloads it (_end).
            self.stale = True
            raise

    def _run(self) -> Run:
        if self.run is None:
            raise RuntimeError(f"run {self.run_id}'s start isn't recorded")
        return self.run

    def _record(self, event: p.RunEvent) -> str:
        run = self._run()
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

    def _end(self, outcome: dict[str, Any], changes: dict[str, Any] | None) -> None:
        if self.stale:
            loaded = self.store.load(UUID(self.run_id))
            if not isinstance(loaded, Run):
                raise TypeError(f"run {self.run_id}'s stream doesn't hold a run")
            self.run = loaded
        run = self._run()
        recording = None
        if self.failure is not None:
            recording = {"failedAt": self.failure[0], "error": self.failure[1].to_data()}
        run.end(outcome, recording, changes)
        self.agent.record(run.collect_events())

    async def end(self, outcome: dict[str, Any], changes: dict[str, Any] | None) -> None:
        await asyncio.to_thread(self._end, outcome, changes)


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
    scratch_root = refuse_scratch_in_theatre(defaults.run_scratch_root(), theatre)
    merged = await asyncio.to_thread(read, store)
    refuse_conflicts(merged)
    what = _from_config(merged, request.actor)
    argv = runner_command(what.runner)
    check_actor(what.actor, merged.config)
    runtime = (
        runtimes.for_run(what.runtime, what.actor, what.model, merged.config, session.env)
        if what.runtime is not None
        else None
    )
    direction = request.direction or ""
    vcs = store.vcs
    base: tuple[str, str] | None = None
    if what.workspace == "worktree":
        base = await asyncio.to_thread(worktree_base, vcs, what.actor)
    if request.rehearse:
        # Every check a flush makes, without writing: a rehearsal changes nothing.
        found = merges(vcs)  # a file git merged is refused, naming troupe flush, as perform would
        refuse(plan(theatre / ".troupe", render(merged.config), merged.files, merged=found))
        return m.PerformResult(
            rehearsal=m.Rehearsal(
                actor=what.actor,
                runner=what.runner,
                stage=m.StageData.from_data(admission.to_data()),
                effect_check=what.effect_check,
                effects=what.effects,
                config=list(what.config),
                character=_summary(what.character),
                direction=_summary(direction),
                workspace=m.RehearsedWorkspace(
                    kind=what.workspace, base=base[0] if base is not None else None
                ),
                runtime=(
                    m.ResolvedRuntime.from_data(runtime.to_data()) if runtime is not None else None
                ),
            )
        )
    for notice in await asyncio.to_thread(sync_files, session, store, merged, send):
        send(_notice(notice))

    run_id = str(uuid4())
    lease = lease_dir(theatre, run_id)
    lease.mkdir(parents=True)
    with directory_lock(lease):
        announce = lambda notice: send(_notice(notice))  # noqa: E731
        artifacts = backends.artifact_store(session)
        direction_ref = await asyncio.to_thread(artifacts.put, direction.encode("utf-8"))
        planned: Planned | None = None
        if base is not None:
            planned = await asyncio.to_thread(
                plan_worktree, vcs, theatre, run_id, base[0], base[1], announce
            )
        recorded_workspace = planned.record(theatre) if planned is not None else {"kind": "theatre"}
        person = store.command(via="cli", actor=person_identity, stage=admission)
        agent = person.acting_as(
            Identity(kind="agent", id=what.actor, source="troupe"), via="runner"
        )
        cancel = session.cancel.bind()
        recorder = _Recorder(
            run_id,
            what,
            store,
            person,
            agent,
            admission.to_data(),
            direction_ref,
            recorded_workspace,
            send,
            cancel,
            runtime,
        )
        await recorder.start()
        send(
            m.Started(
                run_id=run_id,
                worktree=recorded_workspace["path"] if planned is not None else None,
            )
        )
        worktree: Worktree | None = None
        shared_before: SharedState | None = None
        try:
            if planned is not None:
                worktree = await asyncio.to_thread(make_worktree, vcs, planned, announce)
                await recorder.made(worktree)
                shared_before = await asyncio.to_thread(snapshot, vcs, announce)
        except Exception as error:
            await _could_not_start(recorder, run_id, error, backends.limits)
            raise
        workspace = worktree.cwd if worktree is not None else stage.workspace(theatre)
        environment = runner_environment(what.runner, session.env)
        if runtime is not None and runtime.value is not None:
            # After the table's variables, so one already in perform's environment never passes.
            environment[CREDENTIAL_VARIABLE] = runtime.value
        outcome = await run_actor(
            RunnerCommand(list(argv), cwd=workspace, env=environment),
            RunRequest(
                run_id,
                direction,
                workspace,
                what.options,
                character=what.character,
                effects=what.effects,
                runtime=(
                    p.RunStartRuntime.from_data(runtime.run_start())
                    if runtime is not None
                    else None
                ),
                credential=runtime.value if runtime is not None else None,
            ),
            store=artifacts,
            effect=expected_files_for(what, workspace),
            audit=audit_for(
                what, workspace, vcs, worktree.baseline if worktree is not None else None
            ),
            limits=backends.limits,
            on_event=recorder.on_event,
            on_announce=lambda notice: send(_notice(notice)),
            cancel=cancel,
            scratch_root=scratch_root,
        )
        data = outcome.to_data()
        del data["runId"]
        changes = None
        if worktree is not None and shared_before is not None:
            changes = await asyncio.to_thread(
                _changes, vcs, worktree, artifacts, shared_before, announce
            )
        try:
            await recorder.end(data, changes)
        except Exception as error:
            raise _recording_failed(
                run_id, recorder.failure, outcome, ended=_as_troupe_error(error)
            ) from error
        if recorder.failure is not None:
            raise _recording_failed(run_id, recorder.failure, outcome, ended=None)
        history = await asyncio.to_thread(store.history, UUID(run_id))
    [view] = fold_runs(history).values()
    return m.PerformResult(run=view.summary("ended"))


async def _could_not_start(
    recorder: _Recorder, run_id: str, error: Exception, limits: RunLimits | None
) -> None:
    """End a run that failed after its start and before its runner started: could-not-start,
    with ``error``, and no changes, since the runner never ran (account-for-every-worktree design
    D5). The caller raises ``error`` afterwards. When the end can't be recorded either, raises
    run.recording-failed naming both, and the run shows as interrupted."""
    stopped = _as_troupe_error(error)
    data = not_started(run_id, limits, stopped).to_data()
    del data["runId"]
    try:
        await recorder.end(data, None)
    except Exception as ended:
        failed = _as_troupe_error(ended)
        raise TroupeError(
            "run.recording-failed",
            problem=f"Run {run_id} couldn't start: {stopped.problem} Its end couldn't be recorded "
            f"either ({failed.problem}), so status shows it as interrupted.",
            fix=f"{stopped.fix} Then discard the run to remove anything it left: troupe discard "
            f"{run_id[:8]}",
            details={"run": run_id, "error": stopped.to_data(), "endError": failed.to_data()},
        ) from ended


def _changes(
    vcs: Vcs,
    worktree: Worktree,
    artifacts: ArtifactStore,
    before: SharedState,
    announce: Callable[[Notice], None],
) -> dict[str, Any]:
    """A worktree run's changes, for its end: what changed in the repository's shared state,
    announced, and the worktree's diff. A failure to read either is recorded, never raised: the
    run's end must still be recorded, and the worktree is kept."""
    try:
        shared = before.compare(snapshot(vcs, announce))
    except TroupeError as error:
        return {"error": error.to_data()}
    if not shared.empty:
        announce(shared_changed(shared))
    return capture(vcs, worktree, artifacts, shared, announce)


def _recording_failed(
    run_id: str,
    failure: tuple[int, TroupeError] | None,
    outcome: RunOutcome,
    *,
    ended: TroupeError | None,
) -> TroupeError:
    transcript = outcome.transcript
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
        details=_recording_details(run_id, failure, first, outcome, ended=ended),
    )


def _recording_details(
    run_id: str,
    failure: tuple[int, TroupeError] | None,
    first: TroupeError,
    outcome: RunOutcome,
    *,
    ended: TroupeError | None,
) -> dict[str, object]:
    """run.recording-failed's details, leaving out what it can't name: no seq when only the end
    failed, no end error when the end was recorded, no transcript or its format when the runner
    never started."""
    details: dict[str, object] = {"run": run_id, "error": first.to_data()}
    if failure is not None:
        details["failedAt"] = failure[0]
    if ended is not None:
        details["endError"] = ended.to_data()
    if outcome.transcript is not None and outcome.transcript_format is not None:
        details["transcript"] = outcome.transcript
        details["transcriptFormat"] = str(outcome.transcript_format)
    return details


def _notice(notice: Notice) -> m.NoticeUpdate:
    return m.NoticeUpdate(notice=m.NoticeData.of(notice))
