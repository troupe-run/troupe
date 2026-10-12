"""status and logs: runs read back from projections (spec: runs; perform-status-logs design D11 to
D13).

Each query rebuilds what it needs from the event store with the folds in projections. A run's state
is derived: ended when its end is recorded, otherwise from its lease in this clone. The lease is
the platform's lock on ``.troupe/local/runs/<id>/``, which perform holds while the run goes and
the OS releases if perform dies, so a lock nobody holds means the run was interrupted, and no lease
at all means it was started in another clone. Nothing is ever recorded for an interrupted run.
"""

import asyncio
import contextlib
from collections.abc import Iterator
from pathlib import Path
from uuid import UUID

from troupe.core import defaults
from troupe.core.client import messages as m
from troupe.core.client.dispatch import Send
from troupe.core.client.session import Session
from troupe.core.errors import TroupeError
from troupe.core.events import EventStore
from troupe.core.notices import Notice
from troupe.core.runs.aggregate import TOPICS
from troupe.core.runs.perform import Backends, lease_dir
from troupe.core.runs.projections import Recording, RunView, fold_runs
from troupe.platform import locks
from troupe.platform.errors import LockAlreadyHeldError, LockTimeoutError

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
        return "running"


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


def _recordings(store: EventStore) -> Iterator[Recording]:
    low = 1
    while True:
        page = store.recorder.notifications(low, _PAGE, None, TOPICS)
        if not page:
            return
        for _, recording in page:
            yield recording
        low = page[-1][0] + 1


def read_runs(store: EventStore) -> dict[str, RunView]:
    """Every run whose start is recorded, in the local order each was first seen."""
    return {run_id: view for run_id, view in fold_runs(_recordings(store)).items() if view.visible}


def resolve(ref: str, runs: dict[str, RunView]) -> str:
    """The run ``ref`` names: a full id, or a prefix of at least 8 hex digits matching one run."""
    if ref in runs:
        return ref
    matches = sorted(run_id for run_id in runs if run_id.startswith(ref))
    if not matches:
        raise TroupeError(
            "run.not-found",
            problem=f"No run here has an id starting {ref}.",
            fix="Run `troupe status` to list the runs here. A run started in another clone "
            "arrives once it is committed and pulled.",
            details={"run": ref},
        )
    if len(matches) > 1:
        raise TroupeError(
            "run.ambiguous-id",
            problem=f"More than one run has an id starting {ref}: {', '.join(matches)}.",
            fix="Give more of the run's id, enough to match one run.",
            details={"run": ref, "matches": matches},
        )
    return matches[0]


def _summary(view: RunView, theatre: Path, notices: list[Notice]) -> m.RunSummary:
    state = run_state(view, theatre)
    notice = state_notice(view.run_id, state)
    if notice is not None:
        notices.append(notice)
    return view.summary(state)


def _status(request: m.StatusRequest, session: Session, backends: Backends) -> m.StatusResult:
    store = backends.event_store(session)
    runs = read_runs(store)
    notices: list[Notice] = []
    if request.run is not None:
        chosen = [runs[resolve(request.run, runs)]]
    else:
        limit = request.limit or defaults.STATUS_RUNS_LIMIT
        chosen = list(reversed(runs.values()))[:limit]
    summaries = [_summary(view, session.theatre, notices) for view in chosen]
    return m.StatusResult(
        runs=summaries, notices=[m.NoticeData.of(n) for n in [*store.notices(), *notices]]
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


async def logs(
    request: m.LogsRequest, session: Session, send: Send, *, backends: Backends | None = None
) -> m.LogsResult:
    """A run's events in seq order. With follow, each new event is sent as it is recorded, until
    the run ends or stops running; following polls the store at SUBSCRIBE_POLL_SECONDS, as its
    subscription does."""
    backends = backends or Backends()
    store = await asyncio.to_thread(backends.event_store, session)
    runs = await asyncio.to_thread(read_runs, store)
    run_id = resolve(request.run, runs)
    view = await asyncio.to_thread(_log, store, run_id)
    notices: list[Notice] = []
    if request.follow:
        cancel = session.cancel.bind()
        sent = 0
        while True:
            for event in view.log[sent:]:
                send(event)
            sent = len(view.log)
            if view.ended is not None or cancel.is_set():
                break
            if run_state(view, session.theatre) != "running":
                # One last read: the end may have been recorded as the lease was released.
                view = await asyncio.to_thread(_log, store, run_id)
                for event in view.log[sent:]:
                    send(event)
                break
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(cancel.wait(), defaults.SUBSCRIBE_POLL_SECONDS)
            view = await asyncio.to_thread(_log, store, run_id)
    summary = _summary(view, session.theatre, notices)
    return m.LogsResult(
        run=summary,
        events=view.log,
        notices=[m.NoticeData.of(n) for n in [*store.notices(), *notices]],
    )
