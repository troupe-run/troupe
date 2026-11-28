"""Recording one run: its start, each run event and notice in the order they arrive, and its end
(spec: runs, performances; run-notices-in-history design D2 to D7; actor-sequences design D2).

Moved from troupe.core.runs.perform, which re-exports it, when perform became a driver of steps.
"""

import asyncio
import contextlib
import threading
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from troupe.core.client import messages as m
from troupe.core.client.dispatch import Send
from troupe.core.errors import TroupeError
from troupe.core.events import Command, EventStore
from troupe.core.masking import Masker
from troupe.core.notices import Notice
from troupe.core.runs import gate
from troupe.core.runs.aggregate import Run
from troupe.core.runs.backends import Backends as Backends
from troupe.core.runs.backends import lease_dir as lease_dir
from troupe.core.runs.performance import Performance, outcome_of
from troupe.core.runs.plan import (
    ContextFull,
    PerformanceStart,
    Performed,
    _approvers_data,
    _StepPlan,
    _What,
)
from troupe.core.runtimes import RunRuntime
from troupe.core.workspaces import (
    Worktree,
)
from troupe_plugin_sdk import runner as p


def _as_troupe_error(error: BaseException) -> TroupeError:
    if isinstance(error, TroupeError):
        return error
    return TroupeError(
        "internal.unexpected",
        problem=f"troupe hit an unexpected error: {type(error).__name__}: {error}",
        fix="This is a bug in troupe. Please report it at https://github.com/troupe-run/troupe/issues",
    )


@dataclass(frozen=True)
class _Failure:
    """What wasn't recorded first, and why: a run event by its seq, or a notice by its code."""

    error: TroupeError
    seq: int | None = None
    notice: str | None = None

    def to_data(self) -> dict[str, Any]:
        """The run's end's ``recording``: exactly one of failedAt and notice, and the error."""
        named: dict[str, Any] = (
            {"failedAt": self.seq} if self.seq is not None else {"notice": self.notice}
        )
        return {**named, "error": self.error.to_data()}


@dataclass
class _Entry:
    """One thing to record, in the order it reached the recorder: a run event or a notice."""

    event: p.RunEvent | None = None
    notice: dict[str, Any] | None = None
    clones: tuple[str, ...] | None = None
    """The clone mechanisms of a worktree run's made worktree."""
    done: "asyncio.Future[str | None] | None" = None


def _settle(entry: _Entry, at: str | None, error: BaseException | None = None) -> None:
    """Tell ``entry``'s waiter how its recording went, unless nobody is waiting any more: a waiter
    that was cancelled (say, by the run host's start timeout) cancels its future, and setting it
    then would raise and end the writer, with every entry after it left unrecorded."""
    if entry.done is None or entry.done.done():
        return
    if error is not None:
        entry.done.set_exception(error)
    else:
        entry.done.set_result(at)


_DRAIN = _Entry()
"""Tells the writer every entry before it is recorded, so the end can follow."""


class _Recorder:
    """Records one run's events and notices, in the order they arrive, and its end.

    One writer task records every run event and notice through a worker thread, one at a time,
    in the order they reached its queue (run-notices-in-history design D3). A notice can arrive
    from the event loop or from another thread (a workspace operation's timer), and is sent live at
    once, masked; it is queued before the start is recorded too, and the writer starts once the
    start is. A run event's caller waits for it to be recorded; a notice's doesn't. The end waits
    for the queue to empty first.
    """

    def __init__(
        self,
        performance_id: str,
        run_id: str,
        what: "_What",
        store: EventStore,
        person: Command,
        agent: Command,
        admission: dict[str, Any],
        direction_ref: str,
        send: Send,
        cancel: asyncio.Event,
        context_full: ContextFull,
        runtime: RunRuntime | None = None,
        *,
        step: _StepPlan | None = None,
        start: PerformanceStart | None = None,
        performance: Performance | None = None,
    ) -> None:
        self.performance_id = performance_id
        self.run_id = run_id
        self.what = what
        self.step = step if step is not None else _StepPlan(what)
        self.start_of = start
        """The performance's start, recorded with this run's: the first step's only."""
        self.runtime = runtime
        self.context_full = context_full
        self.store = store
        self.stale = False
        self.person = person
        self.agent = agent
        self.admission = admission
        self.direction_ref = direction_ref
        self.workspace: dict[str, Any] = {"kind": "theatre"}
        self.send = send
        self.cancel = cancel
        self.mask = Masker(runtime.value if runtime is not None else None)
        self.loop = asyncio.get_running_loop()
        self.loop_thread = threading.get_ident()
        self.queue: asyncio.Queue[_Entry] = asyncio.Queue()
        self.writer: asyncio.Task[None] | None = None
        self.run: Run | None = None
        self.performance: Performance | None = performance
        self.failure: _Failure | None = None

    def _start(self) -> None:
        approvers = _approvers_data(self.step)
        started: list[Any] = []
        performance = self.performance
        if self.step.position.first:
            begun = self.start_of or PerformanceStart(
                self.performance_id, Performed("actor", self.what.actor), [self.step.recorded()]
            )
            performance = Performance(
                performance_id=self.performance_id,
                performed=begun.performed.to_data(),
                steps=begun.steps,
                direction=self.direction_ref,
                config=list(self.what.config),
            )
            started = list(performance.collect_events())
        run = Run(
            run_id=self.run_id,
            actor=self.what.actor,
            runner_requested=self.what.runner,
            stage=self.admission,
            effect_check=self.what.effect_check.to_data(),
            direction=self.direction_ref,
            config=list(self.what.config),
            workspace=self.workspace,
            on_context_full=self.context_full.to_data(),
            step=self.step.position.index,
            runtime=self.runtime.to_data() if self.runtime is not None else None,
            approvers=approvers,
        )
        # The config version must still be here as the start is written: a person's drop of an
        # abandoned edit between this perform's sync and now refuses the start, never leaving a
        # run naming events that are gone (abandoned-edits design D4). The performance's start is
        # in the same batch, so neither is recorded without the other (performances design D2).
        self.person.record([*started, *run.collect_events()], requires=list(self.what.config))
        self.performance = performance
        self.run = run

    async def start(self, workspace: dict[str, Any]) -> None:
        """Record the run's start, in ``workspace``, before its workspace is made and its runner
        starts; then start recording what's queued, notices raised before the start first."""
        self.workspace = workspace
        await asyncio.to_thread(self._start)
        self.writer = asyncio.create_task(self._write())

    def _made(self, clones: tuple[str, ...]) -> None:
        run = self._run()
        run.made_worktree(list(clones))
        self.person.record(run.collect_events())

    async def made(self, worktree: Worktree) -> None:
        """Record that the run's worktree is made, with its clone mechanisms, after every notice
        raised before it. A failure to record it raises, as before: the run can't start. Once
        something else failed to record, it isn't recorded, and the run is already cancelled."""
        done: asyncio.Future[str | None] = self.loop.create_future()
        self.queue.put_nowait(_Entry(clones=worktree.clones, done=done))
        await done

    def _run(self) -> Run:
        if self.run is None:
            raise RuntimeError(f"run {self.run_id}'s start isn't recorded")
        return self.run

    # Notices

    def notice(self, notice: Notice) -> None:
        """Send ``notice`` live, masked, and queue it for recording. Safe from any thread."""
        data = self.mask.data(notice.to_data())
        if not isinstance(data, dict):
            raise TypeError("a masked notice is still a JSON object")
        self.send(m.NoticeUpdate(notice=m.NoticeData.from_data(data)))
        if threading.get_ident() == self.loop_thread:
            self.queue.put_nowait(_Entry(notice=data))
        else:
            with contextlib.suppress(RuntimeError):  # the loop has closed: perform has returned
                self.loop.call_soon_threadsafe(self.queue.put_nowait, _Entry(notice=data))

    def _note(self, notice: dict[str, Any]) -> None:
        run = self._run()
        run.notice(notice)
        self.person.record(run.collect_events())

    # Run events

    def _record(self, event: p.RunEvent) -> str:
        run = self._run()
        run.report(event.seq, event.to_data())
        [recorded] = self.agent.record(run.collect_events())
        return recorded.at

    async def on_event(self, event: p.RunEvent) -> None:
        if self.failure is not None:
            return
        done: asyncio.Future[str | None] = self.loop.create_future()
        self.queue.put_nowait(_Entry(event=event, done=done))
        at = await done
        if at is None:
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

    # The writer

    async def _write(self) -> None:
        """Record each queued entry in turn, until told to drain. Once a run event or a notice
        fails to record, nothing more is: a gap would break the seq rule, and the history would
        read as whole."""
        while (entry := await self.queue.get()) is not _DRAIN:
            if entry.clones is not None:
                await self._write_made(entry)
                continue
            at: str | None = None
            if self.failure is None:
                try:
                    if entry.event is not None:
                        at = await asyncio.to_thread(self._record, entry.event)
                    elif entry.notice is not None:
                        await asyncio.to_thread(self._note, entry.notice)
                except Exception as error:  # any failure to record stops the run
                    # The aggregate may have counted what wasn't recorded; the end reloads it.
                    self.stale = True
                    self.failure = _Failure(
                        _as_troupe_error(error),
                        seq=entry.event.seq if entry.event is not None else None,
                        notice=str(entry.notice["code"]) if entry.notice is not None else None,
                    )
                    self.cancel.set()
            _settle(entry, at)

    async def _write_made(self, entry: _Entry) -> None:
        if entry.done is None or entry.clones is None:
            raise TypeError("a worktree's made entry has clones and a waiter")
        if self.failure is not None:
            _settle(entry, None)
            return
        try:
            await asyncio.to_thread(self._made, entry.clones)
        except Exception as error:
            # The aggregate may have counted what wasn't recorded; the end reloads it (_end).
            self.stale = True
            _settle(entry, None, error)
            return
        _settle(entry, None)

    async def _drain(self) -> None:
        """Wait until every entry queued so far is recorded, or dropped after a failure."""
        if self.writer is None:
            return
        self.queue.put_nowait(_DRAIN)
        await self.writer
        self.writer = None

    def stop(self) -> None:
        """Stop the writer if perform is leaving without an end (it failed part-way)."""
        if self.writer is not None:
            self.writer.cancel()
            self.writer = None

    # The end

    def _end(self, outcome: dict[str, Any], changes: dict[str, Any] | None) -> None:
        if self.stale:
            loaded = self.store.load(UUID(self.run_id))
            if not isinstance(loaded, Run):
                raise TypeError(f"run {self.run_id}'s stream doesn't hold a run")
            self.run = loaded
        run = self._run()
        recording = self.failure.to_data() if self.failure is not None else None
        run.end(outcome, recording, changes)
        ended = run.collect_events()
        approvers = self.step.approvers
        gated = (
            approvers is not None
            and changes is not None
            and gate.reaches_gate(outcome.get("outcome"), changes)
        )
        if not gated:
            # No gate follows, so nothing more will happen in the performance: it ends with the
            # run, in the same batch (performances design D3).
            performance = self._performance()
            performance.end(outcome_of(outcome.get("outcome"), changes))
            over = performance.collect_events()
            self.store.record_with_lineages(
                [*ended, *over],
                [self.agent.lineage()] * len(ended) + [self.person.lineage()] * len(over),
            )
            return
        if approvers is None or changes is None or not gate.first_is_a_person(approvers.value):
            # troupe goes first, after the end: it keeps the work, ending the performance, or
            # passes the gate to a person (troupes_step).
            self.agent.record(ended)
            return
        # A person first: the cue is recorded with the end, so no perform that stops after the
        # end leaves the run unasked (manual-gates design D3).
        run.raise_cue(approvers.value[0], gate.brief(self.what.actor, "succeeded", changes))
        cue = run.collect_events()
        troupe = gate.troupe_command(self.store, self.person)
        self.store.record_with_lineages(
            [*ended, *cue], [self.agent.lineage()] * len(ended) + [troupe.lineage()] * len(cue)
        )

    def _performance(self) -> Performance:
        if self.performance is None:
            raise RuntimeError(f"performance {self.performance_id}'s start isn't recorded")
        return self.performance

    async def end(self, outcome: dict[str, Any], changes: dict[str, Any] | None) -> None:
        """Record the run's end, once every run event and notice raised before it is recorded."""
        await self._drain()
        await asyncio.to_thread(self._end, outcome, changes)
