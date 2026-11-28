"""A worktree run's gate, and the answers to its cue (spec: gates; manual-gates design D1 to D8).

When a worktree run ends ``succeeded`` with a captured diff, its approvers are tried in order:

- ``troupe`` keeps the changes when they apply cleanly to the working tree, as accept does, with
  troupe's own approval in the acceptance's lineage. When they don't, it passes the gate to the
  next approver, and the pass is recorded with the files that conflict.
- Reaching ``director`` raises a cue with a brief. When ``director`` is first in the list, the cue
  is recorded in the same batch as the run's end, so no perform that stops after the end leaves the
  run unasked (design D3).

troupe's steps are recorded as troupe itself (a system actor), through cli, as part of the perform
command: they share its change id, and its command is their cause. ``approve`` and ``reject`` are a
person's own commands, refused for an agent identity until roles config says who holds a role.
"""

import asyncio
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any
from uuid import UUID

from troupe.core import gates
from troupe.core.client import messages as m
from troupe.core.client.dispatch import Send
from troupe.core.client.session import Session
from troupe.core.errors import TroupeError
from troupe.core.events import Command, EventStore
from troupe.core.files import directory_lock
from troupe.core.identity import Identity
from troupe.core.notices import Notice
from troupe.core.runs.aggregate import Run
from troupe.core.runs.backends import Backends
from troupe.core.runs.changes import (
    SETTLED,
    keep,
    performance_of,
    record_settling,
    settle_lock,
    settled_error,
    view_of,
)
from troupe.core.runs.projections import RunView, fold_runs
from troupe.core.workspaces import remove_worktree


def reaches_gate(outcome: str | None, changes: dict[str, Any] | None) -> bool:
    """Whether a run's end takes it through a gate: it succeeded with a captured diff."""
    return (
        outcome == "succeeded"
        and changes is not None
        and "diff" in changes
        and "error" not in changes
    )


def brief(
    actor: str, outcome: str, changes: dict[str, Any], after: dict[str, Any] | None = None
) -> dict[str, Any]:
    """A cue's brief: whose run, how it ended, what it changed, and the pass that led here."""
    data: dict[str, Any] = {
        "actor": actor,
        "outcome": outcome,
        "diff": changes["diff"],
        "added": changes["added"],
        "modified": changes["modified"],
        "deleted": changes["deleted"],
    }
    if after is not None:
        data["after"] = after
    return data


def troupe_command(store: EventStore, person: Command) -> Command:
    """troupe acting by itself within ``person``'s command: the same change id and performance,
    no stage."""
    return Command(
        store,
        actor=gates.troupe_actor(),
        via="cli",
        reason=None,
        change=person.change,
        performance=person.performance,
    )


def first_is_a_person(approvers: Sequence[str]) -> bool:
    return bool(approvers) and approvers[0] in gates.PERSON_ROLES


def troupes_step(
    store: EventStore,
    theatre: Path,
    data: bytes,
    run_id: str,
    approvers: Sequence[str],
    person: Command,
    announce: Callable[[Notice], None],
) -> None:
    """troupe's turn at a run's gate, after its end: keep the changes, or pass to the next
    approver and raise its cue. Under the run's settle lock, so a person's accept can't race it."""
    command = troupe_command(store, person)
    with directory_lock(settle_lock(theatre, run_id)):
        # This run's own events only: troupe's turn doesn't depend on any other run in the store.
        [view] = fold_runs(store.history(UUID(run_id))).values()
        changes = view.changes() or {}
        if changes.get("state") != "pending":
            return  # settled meanwhile: nothing for troupe to do
        try:
            keep(
                store,
                theatre,
                view,
                changes,
                data,
                rehearse=False,
                reason=None,
                announce=announce,
                command=command,
                approved_as=gates.TROUPE,
                ends="completed",
            )
        except TroupeError as error:
            if error.code != "run.changes-conflict":
                raise
            files = [str(f) for f in error.details["files"]]
            to = approvers[1]
            started = view.started or {}
            outcome = ((view.ended or {}).get("outcome") or {}).get("outcome", "succeeded")
            after = {"approver": gates.TROUPE, "reason": "conflict", "files": files}

            def pass_and_cue(run: Run) -> None:
                run.pass_gate(gates.TROUPE, to, files)
                run.raise_cue(to, brief(started["actor"], outcome, changes, after))

            record_settling(
                store, run_id, None, pass_and_cue, performance=performance_of(view), command=command
            )


# Answering a cue


def _answerable(view: RunView, run_id: str) -> tuple[dict[str, Any], str]:
    """The run's waiting changes and the role their cue is for, or why it can't be answered."""
    changes = view.changes()
    if changes is None:
        raise gates.no_cue(run_id, "none")
    if changes["state"] in SETTLED:
        raise settled_error(view, changes)
    if changes["state"] != "waiting":
        raise gates.no_cue(run_id, changes["state"])
    return changes, changes["cue"]["role"]


def _holder(store: EventStore, role: str) -> Identity:
    """Who is answering, refused unless a person: until roles config, only a person holds
    director (spec: gates, "Whoever runs troupe holds director")."""
    identity = store.identify()
    if not isinstance(identity, Identity) or identity.kind != "human":
        raise gates.not_a_holder(role, getattr(identity, "kind", "unknown"))
    return identity


def _approve(
    request: m.ApproveRequest,
    session: Session,
    backends: Backends,
    announce: Callable[[Notice], None],
) -> m.AcceptResult:
    theatre = session.theatre
    store = backends.event_store(session)
    view = view_of(store, request.run)
    changes, role = _answerable(view, view.run_id)
    identity = _holder(store, role)
    data = backends.artifact_store(session).read(changes["diff"])
    with directory_lock(settle_lock(theatre, view.run_id)):
        view = view_of(store, view.run_id)  # again, inside the lock: another answer may have won
        changes, role = _answerable(view, view.run_id)
        return keep(
            store,
            theatre,
            view,
            changes,
            data,
            rehearse=bool(request.rehearse),
            reason=request.reason,
            announce=announce,
            command=store.command(via="cli", actor=identity, reason=request.reason),
            approved_as=role,
            ends="completed",
        )


def _reject(
    request: m.RejectRequest,
    session: Session,
    backends: Backends,
    announce: Callable[[Notice], None],
) -> m.DiscardResult:
    theatre = session.theatre
    store = backends.event_store(session)
    view = view_of(store, request.run)
    changes, role = _answerable(view, view.run_id)
    identity = _holder(store, role)
    with directory_lock(settle_lock(theatre, view.run_id)):
        view = view_of(store, view.run_id)
        changes, role = _answerable(view, view.run_id)
        if not request.rehearse:
            remove_worktree(store.vcs, theatre, view.run_id, announce)
            record_settling(
                store,
                view.run_id,
                request.reason,
                lambda run: run.reject_changes(role),
                performance=performance_of(view),
                command=store.command(via="cli", actor=identity, reason=request.reason),
                ends="rejected",
            )
    return m.DiscardResult(
        run=view.run_id, worktree=changes["worktree"], rehearsed=bool(request.rehearse), notices=[]
    )


async def approve(
    request: m.ApproveRequest, session: Session, send: Send, *, backends: Backends | None = None
) -> m.AcceptResult:
    """Answer a run's open cue by keeping its changes, with the person's approval."""
    return await asyncio.to_thread(
        _approve, request, session, backends or Backends(), _sender(send)
    )


async def reject(
    request: m.RejectRequest, session: Session, send: Send, *, backends: Backends | None = None
) -> m.DiscardResult:
    """Answer a run's open cue by removing its worktree, recording the rejection."""
    return await asyncio.to_thread(_reject, request, session, backends or Backends(), _sender(send))


def _sender(send: Send) -> Callable[[Notice], None]:
    return lambda notice: send(m.NoticeUpdate(notice=m.NoticeData.of(notice)))
