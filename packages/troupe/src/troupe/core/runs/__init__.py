"""Runs: recording a run of an actor, reading runs back, and settling a worktree run's changes
(spec: runs, run-workspaces; perform-status-logs design D8 to D13; worktree-stage design D6)."""

from collections.abc import Mapping
from typing import Any

from troupe.core.client import messages as m
from troupe.core.client.dispatch import Method, Send
from troupe.core.client.session import Session
from troupe.core.messages import Message
from troupe.core.runs.changes import accept, diff, discard
from troupe.core.runs.perform import perform
from troupe.core.runs.queries import logs, status


async def _perform(request: Any, session: Session, send: Send) -> Message:  # noqa: ANN401
    return await perform(request, session, send)


async def _status(request: Any, session: Session, send: Send) -> Message:  # noqa: ANN401
    return await status(request, session, send)


async def _logs(request: Any, session: Session, send: Send) -> Message:  # noqa: ANN401
    return await logs(request, session, send)


async def _diff(request: Any, session: Session, send: Send) -> Message:  # noqa: ANN401
    return await diff(request, session, send)


async def _accept(request: Any, session: Session, send: Send) -> Message:  # noqa: ANN401
    return await accept(request, session, send)


async def _discard(request: Any, session: Session, send: Send) -> Message:  # noqa: ANN401
    return await discard(request, session, send)


def methods() -> Mapping[str, Method]:
    """The commands and queries runs offer through the client protocol, by name."""
    return {
        "perform": Method(m.PerformRequest, _perform),
        "status": Method(m.StatusRequest, _status),
        "logs": Method(m.LogsRequest, _logs),
        "diff": Method(m.DiffRequest, _diff),
        "accept": Method(m.AcceptRequest, _accept),
        "discard": Method(m.DiscardRequest, _discard),
    }
