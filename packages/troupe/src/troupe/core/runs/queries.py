"""status and logs: runs read back from projections (spec: runs; perform-status-logs design D11 to
D13; watch-event-segments design D6).

Each query rebuilds what it needs from the event store with the folds in projections. A run's state
is derived: ended when its end is recorded, otherwise from its lease in this clone. The lease is
the platform's lock on ``.troupe/local/runs/<id>/``, which perform holds while the run goes and
the OS releases if perform dies, so a lock nobody holds means the run was interrupted, and no lease
at all means it was started in another clone. The OS doesn't promise when it releases a dead
process's lock (Windows), so a held lock whose holder, named in the lease's perform.pid, has ended
means interrupted too (run-test-timing design D4). Nothing is ever recorded for an interrupted run.

Following subscribes through the event store port: the store wakes it when anything is recorded,
whoever wrote it. It has no timer for new events. Its one timer checks the lease, because a perform
that dies writes nothing that could wake it.
"""

import asyncio
import contextlib
import dataclasses
import re
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

from troupe.core import defaults
from troupe.core.client import messages as m
from troupe.core.client.dispatch import Send
from troupe.core.client.session import Session
from troupe.core.errors import TroupeError
from troupe.core.events import EventStore, RecordedEvent
from troupe.core.notices import Notice
from troupe.core.runs.aggregate import TOPICS
from troupe.core.runs.backends import PERFORM_PID_FILE, Backends, lease_dir
from troupe.core.runs.projections import RunView, fold_runs
from troupe.platform import locks, processes
from troupe.platform.errors import (
    LockAlreadyHeldError,
    LockTimeoutError,
    ProcessStateUnknownError,
)

if TYPE_CHECKING:
    from troupe.core.config.entities import Names

_PAGE = 1000


def lease_state(theatre: Path, run_id: str) -> m.State:
    """running, interrupted or unfinished-elsewhere, for a run with no recorded end."""
    lease = lease_dir(theatre, run_id)
    if not lease.is_dir():
        return "unfinished-elsewhere"
    try:
        with locks.hold(lease, timeout=0, announce_after=0):
            return "interrupted"
    except (LockTimeoutError, LockAlreadyHeldError):
        return "interrupted" if _holder_has_ended(lease) else "running"


_PID_FILE = re.compile(rb"([1-9][0-9]*)\n([^\r\n]+)\n")
"""perform.pid as perform writes it: the pid in ASCII decimal, then its namespace token, each
followed by a line feed."""


def _holder_has_ended(lease: Path) -> bool:
    """Whether the process the lease's perform.pid names has ended (design D4, D5).

    Only a pid proven ended, in this process's pid namespace, says so. A missing, unreadable or
    malformed file, a token that isn't this process's own, no token here, a pid still running, or
    one the OS can't answer for, all say no: the lock stays the authority, so the run reads as
    running, as it did before the pid was recorded. A wrong "interrupted" would let discard remove
    a live run's worktree; a wrong "running" only lasts until the OS releases the lock.
    """
    try:
        data = (lease / PERFORM_PID_FILE).read_bytes()
    except OSError:
        return False
    found = _PID_FILE.fullmatch(data)
    token = processes.namespace_token()
    if found is None or token is None or found[2] != token.encode("utf-8"):
        return False
    try:
        return not processes.is_running(int(found[1]))
    except (ValueError, ProcessStateUnknownError):
        return False


def run_state(view: RunView, theatre: Path) -> m.State:
    return "ended" if view.ended is not None else lease_state(theatre, view.run_id)


def state_notice(run_id: str, state: m.State) -> Notice | None:
    if state == "interrupted":
        return Notice(
            "run.interrupted",
            problem=f"Run {run_id} has no recorded end, and the troupe perform that ran it has "
            "stopped: it was interrupted before it could record how the run ended.",
            fix="Check the run's events and transcript for how far it got, then perform it "
            "again if you need to. Nothing is recorded on its behalf.",
            details={"run": run_id},
        )
    if state == "unfinished-elsewhere":
        return Notice(
            "run.unfinished-elsewhere",
            problem=f"Run {run_id} has no recorded end, and it was started in another clone, so "
            "this one can't tell whether it is still going.",
            fix="Check the clone that started it. If it is still going there, its end arrives "
            "here once it is committed and pulled.",
            details={"run": run_id},
        )
    return None


def _recordings(store: EventStore, topics: tuple[str, ...] = TOPICS) -> Iterator[RecordedEvent]:
    low = 1
    while True:
        page = store.recorder.notifications(low, _PAGE, None, topics)
        if not page:
            return
        for _, recording in page:
            yield recording
        low = page[-1][0] + 1


def read_runs(store: EventStore) -> dict[str, RunView]:
    """Every run whose start is recorded, in the local order each was first seen. A run whose
    start names no performance was recorded before performances: reading refuses the store, naming
    every such run and how to fix it (performances design D8)."""
    runs = {run_id: view for run_id, view in fold_runs(_recordings(store)).items() if view.visible}
    older = [run_id for run_id, view in runs.items() if view.performance is None]
    if older:
        raise _recorded_before_performances(store, older)
    return runs


def _recorded_before_performances(store: EventStore, older: list[str]) -> TroupeError:
    """run.recorded-before-performances for ``older``: the event files holding their events, split
    into those that hold nothing else (to remove and commit) and those that hold other events too
    (to keep). troupe never removes them itself, and never reads such a run without a performance
    (contributing/releasing.md, "Records an older troupe wrote")."""
    theirs = {UUID(run_id) for run_id in older}
    files: dict[Path, bool] = {}
    """Each file holding one of their events, and whether it holds anything else."""
    others: set[Path] = set()
    for recording in _recordings(store, ()):
        stream = recording.stream
        if isinstance(stream, UUID) and stream in theirs:
            files.setdefault(recording.path, False)
        else:
            others.add(recording.path)
    shown = {path: _relative(store.theatre, path) for path in files}
    remove = sorted(shown[path] for path in files if path not in others)
    keep = sorted(shown[path] for path in files if path in others)
    listed = ", ".join(run_id[:8] for run_id in older)
    removing = (
        f"remove {', '.join(remove)} and commit that, which loses only those runs"
        if remove
        else "no file holds only those runs, so none can be removed without losing other events"
    )
    kept = f" Keep {', '.join(keep)}: each holds other events too." if keep else ""
    return TroupeError(
        "run.recorded-before-performances",
        problem=f"This theatre holds {len(older)} run(s) recorded before performances (troupe "
        f"0.5.0): {listed}. This troupe doesn't read runs from before then, and doesn't change "
        "them.",
        fix="To read them, use a troupe before 0.5 (troupe-run<0.5). To go on without them, "
        f"{removing}.{kept}",
        details={"runs": older, "remove": remove, "keep": keep},
    )


def _relative(theatre: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(theatre.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def resolve(ref: str, runs: dict[str, RunView]) -> str:
    """The run ``ref`` names: a run's full id or a performance's, or a prefix of at least 8 hex
    digits matching exactly one run or performance. A performance names its run when it has
    exactly one; otherwise it's refused, listing its runs (spec: performances, "A performance id
    names a run where a run id does")."""
    performances: dict[str, list[str]] = {}
    for run_id, view in runs.items():
        if view.performance is not None:
            performances.setdefault(view.performance, []).append(run_id)
    if ref in runs:
        return ref
    if ref in performances:
        return _the_run_of(ref, performances[ref])
    matches = sorted(
        {
            *(run_id for run_id in runs if run_id.startswith(ref)),
            *(performance for performance in performances if performance.startswith(ref)),
        }
    )
    if not matches:
        raise TroupeError(
            "run.not-found",
            problem=f"No run or performance here has an id starting {ref}.",
            fix="Run `troupe status` to list the runs here. A run started in another clone "
            "arrives once it is committed and pulled.",
            details={"run": ref},
        )
    if len(matches) > 1:
        raise TroupeError(
            "run.ambiguous-id",
            problem=f"More than one run or performance has an id starting {ref}: "
            f"{', '.join(matches)}.",
            fix="Give more of the id, enough to match one run or performance.",
            details={"run": ref, "matches": matches},
        )
    [match] = matches
    if match in performances:
        return _the_run_of(match, performances[match])
    return match


def _the_run_of(performance: str, run_ids: list[str]) -> str:
    if len(run_ids) == 1:
        return run_ids[0]
    return_ids = ", ".join(run_ids)
    raise TroupeError(
        "performance.several-runs",
        problem=f"Performance {performance} has {len(run_ids)} runs ({return_ids}), and this "
        "needs one.",
        fix="Name one of its runs instead, by its id or the first 8 characters of it.",
        details={"performance": performance, "runs": run_ids},
    )


def _summary(
    view: RunView, theatre: Path, notices: list[Notice], names: "Names | None" = None
) -> m.RunSummary:
    state = run_state(view, theatre)
    notice = state_notice(view.run_id, state)
    if notice is not None:
        notices.append(notice)
    summary = view.summary(state)
    return _with_name_now(summary, view, names)


def _names(store: EventStore) -> "Names | None":
    """What each actor name at a config version is called now (config-mv design D4). None when
    config's stream can't be read: status and logs read runs, so they still show them, without
    the name now, and every command that uses config says what's wrong with it."""
    from troupe.core.config.stream import read

    try:
        return read(store).names
    except TroupeError:
        return None


def _with_name_now(summary: m.RunSummary, view: RunView, names: "Names | None") -> m.RunSummary:
    """``summary`` with ``actorNow`` when the run's actor was renamed since: the entity its name
    meant at the run's config version, under the name it has now."""
    from troupe.core.config.kinds import ACTORS

    if names is None or view.started is None:
        return summary
    heads = view.started.get("config") or []
    now = names.current(ACTORS, summary.actor, [str(head) for head in heads])
    if now is None or now == summary.actor:
        return summary
    return dataclasses.replace(summary, actor_now=now)


def _status(request: m.StatusRequest, session: Session, backends: Backends) -> m.StatusResult:
    store = backends.event_store(session)
    runs = read_runs(store)
    notices: list[Notice] = []
    cues: list[m.OpenCue] = []
    if request.run is not None:
        chosen = [runs[resolve(request.run, runs)]]
    else:
        limit = request.limit or defaults.STATUS_RUNS_LIMIT
        chosen = list(reversed(runs.values()))[:limit]
        # Every open cue, whatever the limit, newest first (spec: gates, "Status lists every open
        # cue").
        found = (view.open_cue() for view in runs.values())
        cues = sorted((c for c in found if c is not None), key=lambda c: c.raised_at, reverse=True)
    names = _names(store)
    summaries = [_summary(view, session.theatre, notices, names) for view in chosen]
    return m.StatusResult(
        runs=summaries,
        cues=cues,
        notices=[m.NoticeData.of(n) for n in [*store.notices(), *notices]],
    )


async def status(
    request: m.StatusRequest, session: Session, send: Send, *, backends: Backends | None = None
) -> m.StatusResult:
    """One run's summary, or the most recent runs', newest first."""
    del send  # status has no updates
    return await asyncio.to_thread(_status, request, session, backends or Backends())


def _log(store: EventStore, run_id: str) -> RunView:
    [view] = fold_runs(store.history(UUID(run_id)), keep_log=True).values()
    return view


class _Wakeup(threading.Event):
    """A listener for the store's subscription that also wakes a coroutine on ``loop``. The store
    sets it from its own thread."""

    def __init__(self, loop: asyncio.AbstractEventLoop, wake: asyncio.Event) -> None:
        super().__init__()
        self._loop = loop
        self._wake = wake

    def set(self) -> None:
        super().set()
        with contextlib.suppress(RuntimeError):  # the loop has already closed
            self._loop.call_soon_threadsafe(self._wake.set)


async def _woken(wake: asyncio.Event, cancel: asyncio.Event, timeout: float) -> bool:
    """Wait for a wake, a cancel or ``timeout``. Whether it was a wake."""
    waits = [asyncio.ensure_future(wake.wait()), asyncio.ensure_future(cancel.wait())]
    _, pending = await asyncio.wait(waits, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
    for waiting in pending:
        waiting.cancel()
    return wake.is_set()


def _once(notices: list[Notice]) -> list[Notice]:
    """Each notice once, by code and path, keeping the first."""
    seen: set[tuple[str, str | None]] = set()
    kept: list[Notice] = []
    for notice in notices:
        if (notice.code, notice.path) not in seen:
            seen.add((notice.code, notice.path))
            kept.append(notice)
    return kept


async def logs(
    request: m.LogsRequest, session: Session, send: Send, *, backends: Backends | None = None
) -> m.LogsResult:
    """A run's log: its events in seq order and its recorded notices, each in its recorded place.
    With follow, each new entry is sent as it is recorded, until the run ends or stops running.
    Following listens to the store's subscription, which wakes it whenever anything is recorded; a
    wake re-reads the run. Every LOGS_LEASE_CHECK_SECONDS it also checks that the run is still
    running. If the store can only poll, its notice is sent at once.
    """
    backends = backends or Backends()
    store = await asyncio.to_thread(backends.event_store, session)
    runs = await asyncio.to_thread(read_runs, store)
    run_id = resolve(request.run, runs)
    if not request.follow:
        view = await asyncio.to_thread(_log, store, run_id)
        notices: list[Notice] = []
        names = await asyncio.to_thread(_names, store)
        summary = _summary(view, session.theatre, notices, names)
        return m.LogsResult(
            run=summary,
            log=view.log,
            notices=[m.NoticeData.of(n) for n in [*store.notices(), *notices]],
        )
    cancel = session.cancel.bind()
    wake = asyncio.Event()
    listener = _Wakeup(asyncio.get_running_loop(), wake)
    # Listen before the first read, so nothing recorded between the two is missed.
    await asyncio.to_thread(store.recorder.listen, listener)
    try:
        found = await asyncio.to_thread(store.notices)
        for notice in found:
            if notice.code == "events.subscription-polling":
                send(m.NoticeUpdate(notice=m.NoticeData.of(notice)))
        view = await asyncio.to_thread(_log, store, run_id)
        sent = 0
        while True:
            for entry in view.log[sent:]:
                send(entry)
            sent = len(view.log)
            if view.ended is not None or cancel.is_set():
                break
            if run_state(view, session.theatre) != "running":
                # One last read: the end may have been recorded as the lease was released.
                view = await asyncio.to_thread(_log, store, run_id)
                for entry in view.log[sent:]:
                    send(entry)
                break
            if await _woken(wake, cancel, defaults.LOGS_LEASE_CHECK_SECONDS):
                wake.clear()  # before reading, so a write during the read wakes the next wait
                view = await asyncio.to_thread(_log, store, run_id)
        found.extend(await asyncio.to_thread(store.notices))
    finally:
        await asyncio.to_thread(store.recorder.unlisten, listener)
    notices = []
    names = await asyncio.to_thread(_names, store)
    summary = _summary(view, session.theatre, notices, names)
    return m.LogsResult(
        run=summary,
        log=view.log,
        notices=[m.NoticeData.of(n) for n in _once([*found, *notices])],
    )
