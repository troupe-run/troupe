"""diff, accept and discard: what a person does with a worktree run's changes (spec:
run-workspaces; worktree-stage design D6, D7).

``diff`` reads the diff a run's end references from the artifact store, verified. ``accept``
applies it to the theatre's working tree, unstaged and all or nothing, records that, then removes
the run's worktree. ``discard`` removes the worktree, then records that. Each refuses, before it
changes anything, a run that isn't a worktree run, isn't in a state to settle, or was already
settled: settling is final. Both take the run's settle lock, ``.troupe/local/runs/<id>/settle``,
and read the run again inside it, so two at once can't both settle it.

Accepting records its event after the files are written. If recording fails, the files have
changed and nothing says so, and the error names the run: the other order would record a claim
that never came true. Either way nothing is lost: the diff stays in the artifact store.
"""

import asyncio
import base64
import contextlib
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import UUID

from troupe.core.client import messages as m
from troupe.core.client.dispatch import Send
from troupe.core.client.session import Session
from troupe.core.errors import TroupeError
from troupe.core.events import EventStore
from troupe.core.files import directory_lock
from troupe.core.notices import Notice
from troupe.core.runs.aggregate import Run
from troupe.core.runs.perform import Backends, lease_dir
from troupe.core.runs.projections import RunView
from troupe.core.runs.queries import read_runs, resolve, run_state
from troupe.core.workspaces import remove_worktree, worktree_path


def _view(store: EventStore, ref: str) -> RunView:
    runs = read_runs(store)
    return runs[resolve(ref, runs)]


def _worktree_changes(view: RunView) -> dict[str, Any]:
    changes = view.changes()
    if changes is None:
        raise TroupeError(
            "run.not-a-worktree",
            problem=f"Run {view.run_id} worked in the theatre, so its changes are already among "
            "your files: there is nothing to show, accept or discard.",
            fix="Use git to see what it changed: git status, git diff.",
            details={"run": view.run_id},
        )
    return changes


def _not_ended(view: RunView, state: m.State) -> TroupeError:
    return TroupeError(
        "run.not-ended",
        problem=f"Run {view.run_id} is {state}: it has no recorded end, so its changes aren't "
        "captured.",
        fix=f"Wait for it to end (troupe logs {view.run_id[:8]} --follow), or discard it if it was "
        "interrupted.",
        details={"run": view.run_id, "state": state},
    )


def _settled(view: RunView, changes: dict[str, Any]) -> TroupeError:
    return TroupeError(
        "run.changes-settled",
        problem=f"Run {view.run_id}'s changes were already {changes['state']}, at "
        f"{changes['settledAt']}.",
        fix="Nothing more can be done with them: settling a run's changes is final.",
        details={"run": view.run_id, "settled": changes["state"], "at": changes["settledAt"]},
    )


def _acceptable(view: RunView, theatre: Path) -> dict[str, Any]:
    """The run's pending changes, or the refusal that says why they can't be accepted."""
    changes = _worktree_changes(view)
    state = run_state(view, theatre)
    if state != "ended":
        raise _not_ended(view, state)
    if changes["state"] in ("accepted", "discarded"):
        raise _settled(view, changes)
    if changes["state"] == "none":
        raise TroupeError(
            "run.no-changes",
            problem=f"Run {view.run_id} changed nothing in its worktree, so there is nothing to "
            "accept.",
            fix=f"Discard it to remove its worktree: troupe discard {view.run_id[:8]}",
            details={"run": view.run_id, "worktree": changes["worktree"]},
        )
    if changes["state"] == "uncaptured":
        details: dict[str, Any] = {"run": view.run_id, "worktree": changes["worktree"]}
        if "error" in changes:
            details["error"] = changes["error"]
        raise TroupeError(
            "run.changes-uncaptured",
            problem=f"Run {view.run_id}'s changes weren't captured, so they can't be accepted.",
            fix=f"Look at what it wrote in {changes['worktree']}, then discard it: troupe discard "
            f"{view.run_id[:8]}",
            path=changes["worktree"],
            details=details,
        )
    return changes


async def diff(
    request: m.DiffRequest, session: Session, send: Send, *, backends: Backends | None = None
) -> m.DiffResult:
    """The diff a worktree run's end references, verified against its reference."""
    backends = backends or Backends()
    store = await asyncio.to_thread(backends.event_store, session)
    view = await asyncio.to_thread(_view, store, request.run)
    changes = _worktree_changes(view)
    state = run_state(view, session.theatre)
    if state != "ended" and changes["state"] != "discarded":
        raise _not_ended(view, state)
    if changes["state"] == "uncaptured":
        _acceptable(view, session.theatre)  # raises run.changes-uncaptured, naming the worktree
    base = view.workspace["base"]
    if "diff" not in changes:
        return m.DiffResult(run=view.run_id, base=base, changes=m.ChangesData.from_data(changes))
    data = await asyncio.to_thread(backends.artifact_store(session).read, changes["diff"])
    try:
        patch, encoding = data.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        patch, encoding = base64.b64encode(data).decode("ascii"), "base64"
    return m.DiffResult(
        run=view.run_id,
        base=base,
        changes=m.ChangesData.from_data(changes),
        patch=patch,
        encoding=encoding,  # type: ignore[arg-type]
    )


def _settle_lock(theatre: Path, run_id: str) -> Path:
    path = lease_dir(theatre, run_id) / "settle"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _record(
    store: EventStore, run_id: str, reason: str | None, settle: Callable[[Run], None]
) -> None:
    run = store.load(UUID(run_id))
    if not isinstance(run, Run):
        raise TypeError(f"run {run_id}'s stream doesn't hold a run")
    settle(run)
    store.command(via="cli", actor=store.identify(), reason=reason).record(run.collect_events())


def _accept(
    request: m.AcceptRequest,
    session: Session,
    backends: Backends,
    announce: Callable[[Notice], None],
) -> m.AcceptResult:
    theatre = session.theatre
    store = backends.event_store(session)
    store.identify()  # who is accepting: refused before anything changes when no one answers
    view = _view(store, request.run)
    changes = _acceptable(view, theatre)
    data = backends.artifact_store(session).read(changes["diff"])
    vcs = store.vcs
    with directory_lock(_settle_lock(theatre, view.run_id)):
        view = _view(store, view.run_id)  # again, inside the lock: another accept may have won
        changes = _acceptable(view, theatre)
        patch = worktree_path(theatre, view.run_id).with_name(f"{view.run_id}.accept.diff")
        patch.write_bytes(data)
        try:
            applicability = vcs.check_apply(patch)
            if not applicability.applies:
                raise TroupeError(
                    "run.changes-conflict",
                    problem=f"Run {view.run_id}'s diff doesn't apply cleanly to your working "
                    f"tree: {', '.join(applicability.failing)} changed since the run started. "
                    "Nothing was changed.",
                    fix=f"See the diff with troupe diff {view.run_id[:8]}, and the run's files in "
                    f"{changes['worktree']}. To merge by hand: troupe diff {view.run_id[:8]} | "
                    "git apply --3way",
                    path=changes["worktree"],
                    details={
                        "run": view.run_id,
                        "diff": changes["diff"],
                        "files": list(applicability.failing),
                        "worktree": changes["worktree"],
                    },
                )
            if request.rehearse:
                return m.AcceptResult(
                    run=view.run_id, files=list(applicability.files), rehearsed=True, notices=[]
                )
            files = vcs.apply(patch)
        finally:
            with contextlib.suppress(FileNotFoundError):
                patch.unlink()
        _record(
            store,
            view.run_id,
            request.reason,
            lambda run: run.accept_changes(changes["diff"], list(files)),
        )
    notices: list[m.NoticeData] = []
    try:
        remove_worktree(vcs, theatre, view.run_id, announce)
    except TroupeError:
        notice = _not_removed(theatre, view.run_id, changes["worktree"])
        announce(notice)
        notices.append(m.NoticeData.of(notice))
    return m.AcceptResult(run=view.run_id, files=list(files), rehearsed=False, notices=notices)


def _not_removed(theatre: Path, run_id: str, worktree: str) -> Notice:
    return Notice(
        "workspace.not-removed",
        problem=f"Run {run_id}'s changes were accepted, and its worktree at {worktree} couldn't be "
        "removed.",
        fix=f"Remove it with git worktree remove --force {worktree}. Nothing in it is needed now.",
        path=str(theatre / worktree),
        details={"worktree": worktree},
    )


def _discard(
    request: m.DiscardRequest,
    session: Session,
    backends: Backends,
    announce: Callable[[Notice], None],
) -> m.DiscardResult:
    theatre = session.theatre
    store = backends.event_store(session)
    store.identify()
    view = _view(store, request.run)

    def check(view: RunView) -> dict[str, Any]:
        changes = _worktree_changes(view)
        state = run_state(view, theatre)
        if state in ("running", "unfinished-elsewhere"):
            raise _not_ended(view, state)
        if changes["state"] in ("accepted", "discarded"):
            raise _settled(view, changes)
        return changes

    changes = check(view)
    with directory_lock(_settle_lock(theatre, view.run_id)):
        view = _view(store, view.run_id)
        changes = check(view)
        if not request.rehearse:
            remove_worktree(store.vcs, theatre, view.run_id, announce)
            _record(store, view.run_id, request.reason, lambda run: run.discard_changes())
    return m.DiscardResult(
        run=view.run_id, worktree=changes["worktree"], rehearsed=bool(request.rehearse), notices=[]
    )


async def accept(
    request: m.AcceptRequest, session: Session, send: Send, *, backends: Backends | None = None
) -> m.AcceptResult:
    """Apply a worktree run's diff to the theatre's working tree, record it, and remove the
    run's worktree."""
    return await asyncio.to_thread(_accept, request, session, backends or Backends(), _sender(send))


async def discard(
    request: m.DiscardRequest, session: Session, send: Send, *, backends: Backends | None = None
) -> m.DiscardResult:
    """Remove a worktree run's worktree, and record that its changes were discarded."""
    return await asyncio.to_thread(
        _discard, request, session, backends or Backends(), _sender(send)
    )


def _sender(send: Send) -> Callable[[Notice], None]:
    return lambda notice: send(m.NoticeUpdate(notice=m.NoticeData.of(notice)))
