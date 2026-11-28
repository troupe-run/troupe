"""perform: run one actor, and record the run (spec: runs, stages, policy, run-workspaces;
perform-status-logs design D4, D5, D8, D9, D11; worktree-stage design D8; account-for-every-worktree
design D1, D2, D5; run-notices-in-history design D2 to D7).

Everything that can refuse runs first, before a runner starts or anything is written: who is
acting, the policy, the stage's admission, the runner's name, and, for a worktree run, whether the
theatre can have one. Then perform mints the run id, takes the run's lease, stores the direction
as an artifact, plans the run's worktree, and records the run's start, so from here on an event
names the run, and its worktree, before any part of the worktree exists: however perform stops,
status shows the run and discard can clear it. Then it makes the worktree and records that, and
runs the host in the workspace. A failure between the start and the runner ends the run
could-not-start, then fails perform with that error. When the host returns, a worktree run's
changes are captured into the artifact store, with what changed in the repository's shared state,
and recorded in the run's end. Each run event is recorded as it arrives, and each notice raised for
the run from when its id is minted, in the order they arrive, through a worker thread so the event
store's fsyncs and git calls stay off the event loop, and the run's end is recorded once the host
returns and everything before it is. Notices are still sent live as they're raised.

A recording failure never raises into the run host: it cancels the run, no later event or notice is
recorded (a gap would break the seq rule), the end is still attempted with what failed, and then
perform fails with run.recording-failed.
"""

import asyncio
import contextlib
import functools
import hashlib
import os
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
from troupe.core.config.kinds import check_actor
from troupe.core.config.merge import Merged
from troupe.core.errors import TroupeError
from troupe.core.events import Command, EventStore
from troupe.core.events.lineage import Actor
from troupe.core.files import directory_lock, replace_file
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
from troupe.core.runs import gate
from troupe.core.runs.backends import PERFORM_PID_FILE
from troupe.core.runs.backends import Backends as Backends
from troupe.core.runs.backends import lease_dir as lease_dir
from troupe.core.runs.briefs import (
    Earlier,
    changed_files,
    direction_for,
    final_message,
    history_files,
)
from troupe.core.runs.changes import landing
from troupe.core.runs.performance import Performance
from troupe.core.runs.plan import ContextFull as ContextFull
from troupe.core.runs.plan import (
    PerformanceStart,
    plan_steps,
)
from troupe.core.runs.plan import _from_config as _from_config
from troupe.core.runs.plan import _rehearsed_approvers as _rehearsed_approvers
from troupe.core.runs.plan import _StepPlan as _StepPlan
from troupe.core.runs.plan import _What as _What
from troupe.core.runs.plan import resolve_context_full as resolve_context_full
from troupe.core.runs.projections import RunView, fold_runs
from troupe.core.runs.queries import refuse_runs_before_performances
from troupe.core.runs.recording import _as_troupe_error as _as_troupe_error
from troupe.core.runs.recording import _Failure
from troupe.core.runs.recording import _Recorder as _Recorder
from troupe.core.runtimes import RunRuntime
from troupe.core.stages import load_stage
from troupe.core.vcs import SharedState, Vcs
from troupe.core.workspaces import (
    Planned,
    Worktree,
    build_on,
    capture,
    make_worktree,
    plan_worktree,
    remove_worktree,
    shared_changed,
    snapshot,
    worktree_base,
)
from troupe.platform.processes import namespace_token
from troupe_plugin_sdk import runner as p
from troupe_plugin_sdk.credential import CREDENTIAL_VARIABLE
from troupe_plugin_sdk.effects import Effects


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


def _summary(text: str | None) -> m.TextSummary | None:
    if not text:
        return None
    digest = "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()
    return m.TextSummary(hash=digest, length=len(text))


def _pid_file() -> bytes:
    """perform.pid: this process's id, then its namespace token, each on its own line. With no
    token the pid is written alone, and no reader trusts it (run-test-timing design D5)."""
    token = namespace_token()
    lines = [str(os.getpid())] if token is None else [str(os.getpid()), token]
    return "".join(f"{line}\n" for line in lines).encode("utf-8")


def _ignore(_: object) -> None:
    """Drops an update: the rehearsed sync before the real one reports nothing."""


@dataclass(frozen=True)
class _Prepared:
    """What every step of one perform shares: who is acting, the stage and what admitted it, the
    store, and where runs' scratch directories go."""

    session: Session
    send: Send
    backends: Backends
    store: EventStore
    person: Actor
    stage: Any
    admission: Any
    policy: Any
    scratch_root: Path


@dataclass(frozen=True)
class _Ready:
    """A step resolved for running: its plan, the runner's command, its context policy and its
    runtime as they resolved (everything that can refuse it has passed)."""

    step: _StepPlan
    argv: list[str]
    context_full: ContextFull
    runtime: RunRuntime | None


async def perform(
    request: m.PerformRequest, session: Session, send: Send, *, backends: Backends | None = None
) -> m.PerformResult:
    """Run the actor ``request`` names and record the run; the result is the recorded run."""
    backends = backends or Backends()
    store = await asyncio.to_thread(backends.event_store, session)
    person_identity = await asyncio.to_thread(store.identify)
    stage = load_stage(defaults.STAGE)
    policy = read_policy(session.env)
    admission = stage.admit(policy)
    scratch_root = refuse_scratch_in_theatre(defaults.run_scratch_root(), session.theatre)
    prepared = _Prepared(
        session, send, backends, store, person_identity, stage, admission, policy, scratch_root
    )
    # Imported here, so the queries and changes that share this module don't load config's
    # handlers (cli-starts-fast design D5). The sync sweeps hand edits into config first, and makes
    # the files what config says: a rehearsal does every check and records and writes nothing
    # (spec: config-hand-edits, "Every command that uses config sweeps first").
    from troupe.core.config.commands import sync_files

    # First as a rehearsal: every check the sync makes, and the config it would leave, so a
    # perform refused below records and writes nothing. A rehearsed perform shows what it found.
    quiet: Send = send if request.rehearse else _ignore
    synced = await asyncio.to_thread(
        functools.partial(sync_files, session, store, quiet, rehearse=True)
    )
    _, planned = plan_steps(synced.merged, request.actor)
    steps = [_ready(prepared, step, synced.merged) for step in planned]
    direction = request.direction or ""
    base: tuple[str, str] | None = None
    if any(ready.step.what.workspace == "worktree" for ready in steps):
        base = await asyncio.to_thread(worktree_base, store.vcs, steps[0].step.what.actor)
    # A theatre holding runs from before performances is refused here, before anything runs or is
    # recorded, rather than at troupe's turn at the gate, after the work (performances design D8).
    await asyncio.to_thread(refuse_runs_before_performances, store)
    if request.rehearse:
        return m.PerformResult(rehearsal=_rehearsal(prepared, steps[0], direction, base))
    # Now for real, just before the run: hand edits recorded, files written. The run uses the
    # config this leaves, and records its version.
    synced = await asyncio.to_thread(functools.partial(sync_files, session, store, send))
    performed, planned = plan_steps(synced.merged, request.actor)
    steps = [_ready(prepared, step, synced.merged) for step in planned]
    performance_id = str(uuid4())
    start = PerformanceStart(performance_id, performed, [ready.step.recorded() for ready in steps])
    summary = await _drive(prepared, steps, performance_id, direction, base, start=start)
    return m.PerformResult(run=summary)


@dataclass(frozen=True)
class _BuiltOn:
    """What a flow's later step is built on: the run of the step before, and the performance's
    diff so far, None when nothing has changed yet (actor-sequences design D3)."""

    run_id: str
    patch: str | None


async def _drive(
    prepared: _Prepared,
    steps: list[_Ready],
    performance_id: str,
    direction: str,
    base: tuple[str, str] | None,
    *,
    start: PerformanceStart | None = None,
    earlier: list[Earlier] | None = None,
    built_on: _BuiltOn | None = None,
) -> m.RunSummary:
    """Run ``steps`` in order, each built on the one before, until the last step's gate, a gate
    that waits, or a step that doesn't succeed; the last run's summary. ``earlier`` are the steps
    that ran before ``steps[0]``, when approve carries a waiting flow on (actor-sequences design
    D2, D7)."""
    store, artifacts = prepared.store, prepared.backends.artifact_store(prepared.session)
    done: list[Earlier] = list(earlier or [])
    summary: m.RunSummary | None = None
    for ready in steps:
        performance = None
        if not ready.step.position.first:
            loaded = await asyncio.to_thread(store.load, UUID(performance_id))
            performance = loaded if isinstance(loaded, Performance) else None
        told = direction_for(direction, ready.step.own_direction, done)
        view = await _run_step(
            prepared,
            ready,
            performance_id,
            told,
            base,
            start=start if ready.step.position.first else None,
            performance=performance,
            built_on=built_on,
            history=history_files(done),
        )
        summary = view.summary("ended")
        changes = summary.changes.to_data() if summary.changes is not None else {}
        goes_on = summary.outcome == "succeeded" and changes.get("state") in ("approved", "none")
        if ready.step.position.last or not goes_on:
            return summary
        done.append(await asyncio.to_thread(_earlier, store, artifacts, ready, view))
        work = changes.get("sofar") or changes.get("diff") or (built_on.patch if built_on else None)
        built_on = _BuiltOn(view.run_id, work)
    if summary is None:
        raise RuntimeError("a performance has at least one step")
    return summary


def _earlier(store: EventStore, artifacts: ArtifactStore, ready: _Ready, view: RunView) -> Earlier:
    """The step that just ran, as later steps are told about it and read its history."""
    [logged] = fold_runs(store.history(UUID(view.run_id)), keep_log=True).values()
    changes = view.changes() or {}
    diff = artifacts.read(changes["diff"]) if "diff" in changes else None
    outcome = ((view.ended or {}).get("outcome") or {}).get("outcome", "ended")
    return Earlier(
        ready.step.position.index,
        ready.step.what.actor,
        str(outcome),
        changed_files(diff),
        final_message(view.ended),
        diff,
        tuple(logged.log),
    )


def _ready(prepared: _Prepared, step: _StepPlan, merged: Merged) -> _Ready:
    """``step`` with every check that can refuse it made: its actor's config, its runner, its
    context policy and its runtime."""
    what = step.what
    argv = runner_command(what.runner)
    check_actor(what.actor, merged.config)
    context_full = resolve_context_full(
        what.actor, what.on_context_full, prepared.policy.compaction
    )
    runtime = (
        runtimes.for_run(
            what.runtime,
            what.actor,
            what.model,
            merged.config,
            prepared.session.env,
            runner=what.runner,
        )
        if what.runtime is not None
        else None
    )
    return _Ready(step, list(argv), context_full, runtime)


def _rehearsal(
    prepared: _Prepared, ready: _Ready, direction: str, base: tuple[str, str] | None
) -> m.Rehearsal:
    what, runtime = ready.step.what, ready.runtime
    return m.Rehearsal(
        actor=what.actor,
        runner=what.runner,
        stage=m.StageData.from_data(prepared.admission.to_data()),
        effect_check=what.effect_check,
        effects=what.effects,
        config=list(what.config),
        character=_summary(what.character),
        direction=_summary(direction),
        workspace=m.RehearsedWorkspace(
            kind=what.workspace,
            base=base[0] if base is not None and what.workspace == "worktree" else None,
        ),
        runtime=m.ResolvedRuntime.from_data(runtime.to_data()) if runtime is not None else None,
        approvers=_rehearsed_approvers(ready.step),
    )


async def _run_step(
    prepared: _Prepared,
    ready: _Ready,
    performance_id: str,
    direction: str,
    base: tuple[str, str] | None,
    *,
    start: PerformanceStart | None = None,
    performance: Performance | None = None,
    built_on: _BuiltOn | None = None,
    history: dict[str, bytes] | None = None,
) -> RunView:
    """Run one step of a performance as a run, from its lease to its gate, and return the run as
    recorded. The first step's start records the performance's (``start``); a later one is given
    the ``performance`` it's a step of."""
    session, store, backends, send = (
        prepared.session,
        prepared.store,
        prepared.backends,
        prepared.send,
    )
    theatre, vcs, stage = session.theatre, store.vcs, prepared.stage
    step, what, runtime, context_full = (
        ready.step,
        ready.step.what,
        ready.runtime,
        ready.context_full,
    )
    run_id = str(uuid4())
    lease = lease_dir(theatre, run_id)
    lease.mkdir(parents=True)
    with directory_lock(lease):
        # Before the start is recorded, so any run that can be seen has it (run-test-timing D4, D5).
        await asyncio.to_thread(replace_file, lease / PERFORM_PID_FILE, _pid_file())
        artifacts = backends.artifact_store(session)
        direction_ref = await asyncio.to_thread(artifacts.put, direction.encode("utf-8"))
        person = store.command(
            via="cli", actor=prepared.person, stage=prepared.admission, performance=performance_id
        )
        agent = person.acting_as(
            Identity(kind="agent", id=what.actor, source="troupe"), via="runner"
        )
        cancel = session.cancel.bind()
        # From here every notice is the run's: sent live, and recorded in its history
        # (run-notices-in-history design D2).
        recorder = _Recorder(
            performance_id,
            run_id,
            what,
            store,
            person,
            agent,
            prepared.admission.to_data(),
            direction_ref,
            send,
            cancel,
            context_full,
            runtime,
            step=step,
            start=start,
            performance=performance,
        )
        try:
            announce = recorder.notice
            planned: Planned | None = None
            if base is not None and what.workspace == "worktree":
                planned = await asyncio.to_thread(
                    plan_worktree, vcs, theatre, run_id, base[0], base[1], announce
                )
            recorded_workspace = (
                planned.record(theatre, built_on=built_on.run_id if built_on else None)
                if planned is not None
                else {"kind": "theatre"}
            )
            await recorder.start(recorded_workspace)
            if start is not None:
                send(
                    m.PerformanceStarted(
                        performance_id=performance_id,
                        performed=m.Performed(kind=start.performed.kind, name=start.performed.name),
                        steps=step.position.total,
                    )
                )
            send(
                m.Started(
                    run_id=run_id,
                    performance_id=performance_id,
                    step=step.position.index,
                    actor=what.actor,
                    worktree=recorded_workspace["path"] if planned is not None else None,
                )
            )
            worktree: Worktree | None = None
            shared_before: SharedState | None = None
            try:
                if planned is not None:
                    worktree = await asyncio.to_thread(make_worktree, vcs, planned, announce)
                    worktree = await asyncio.to_thread(
                        _build, prepared, worktree, built_on, history or {}, announce
                    )
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
                RunnerCommand(list(ready.argv), cwd=workspace, env=environment),
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
                    on_context_full=context_full.value,
                ),
                store=artifacts,
                effect=expected_files_for(what, workspace),
                audit=audit_for(
                    what,
                    workspace,
                    vcs,
                    (worktree.own_baseline or worktree.baseline) if worktree is not None else None,
                ),
                limits=backends.limits,
                on_event=recorder.on_event,
                on_announce=announce,
                cancel=cancel,
                scratch_root=prepared.scratch_root,
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
            await _troupes_turn(
                step,
                str(data.get("outcome")),
                changes,
                artifacts,
                store,
                theatre,
                run_id,
                person,
                announce,
            )
            recorded = await asyncio.to_thread(store.history, UUID(run_id))
        finally:
            recorder.stop()
    [view] = fold_runs(recorded).values()
    return view


def _build(
    prepared: _Prepared,
    worktree: Worktree,
    built_on: _BuiltOn | None,
    history: dict[str, bytes],
    announce: Callable[[Notice], None],
) -> Worktree:
    """A flow's later step's worktree: the performance's diff so far applied inside it, the step
    before's worktree removed (its work lives on here), and the earlier steps' history written
    where the step can read it (actor-sequences design D3, D5, D6)."""
    if built_on is None:
        return worktree
    vcs = prepared.store.vcs
    if built_on.patch is not None:
        patch = worktree.path.parent / f"{worktree.path.name}.sofar.diff"
        artifacts = prepared.backends.artifact_store(prepared.session)
        patch.write_bytes(artifacts.read(built_on.patch))
        try:
            worktree = build_on(vcs, worktree, patch, announce)
        finally:
            with contextlib.suppress(FileNotFoundError):
                patch.unlink()
    for path, data in history.items():
        target = worktree.cwd.joinpath(*path.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    remove_worktree(vcs, prepared.session.theatre, built_on.run_id, announce)
    return worktree


async def _troupes_turn(
    step: _StepPlan,
    outcome: str,
    changes: dict[str, Any] | None,
    artifacts: ArtifactStore,
    store: EventStore,
    theatre: Path,
    run_id: str,
    person: Command,
    announce: Callable[[Notice], None],
) -> None:
    """troupe's turn at a run's gate, when its list starts with troupe: keep the changes, or pass
    and raise a cue (spec: gates; manual-gates design D3). A list that starts with a person had
    its cue recorded with the end."""
    approvers = step.approvers
    if (
        approvers is None
        or changes is None
        or not gate.reaches_gate(outcome, changes)
        or gate.first_is_a_person(approvers.value)
    ):
        return
    patch = await asyncio.to_thread(artifacts.read, landing(changes))
    await asyncio.to_thread(
        gate.troupes_step, store, theatre, patch, run_id, approvers.value, person, announce
    )


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
    failure: _Failure | None,
    outcome: RunOutcome,
    *,
    ended: TroupeError | None,
) -> TroupeError:
    transcript = outcome.transcript
    first = failure.error if failure is not None else ended
    if first is None:
        raise ValueError("a recording failure needs something that failed")
    if failure is None:
        where = "for the run's end"
    elif failure.seq is not None:
        where = f"from run event {failure.seq} on"
    else:
        where = f"from the notice {failure.notice} on"
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
    failure: _Failure | None,
    first: TroupeError,
    outcome: RunOutcome,
    *,
    ended: TroupeError | None,
) -> dict[str, object]:
    """run.recording-failed's details, leaving out what it can't name: no seq when no run event
    failed, no notice when no notice failed, no end error when the end was recorded, no transcript
    or its format when the runner never started."""
    details: dict[str, object] = {"run": run_id, "error": first.to_data()}
    if failure is not None and failure.seq is not None:
        details["failedAt"] = failure.seq
    if failure is not None and failure.notice is not None:
        details["notice"] = failure.notice
    if ended is not None:
        details["endError"] = ended.to_data()
    if outcome.transcript is not None and outcome.transcript_format is not None:
        details["transcript"] = outcome.transcript
        details["transcriptFormat"] = str(outcome.transcript_format)
    return details
