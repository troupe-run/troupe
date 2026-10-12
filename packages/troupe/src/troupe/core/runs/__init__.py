"""Runs: recording a run of an actor, and reading runs back (spec: runs; perform-status-logs
design D8 to D13)."""

from collections.abc import Mapping
from typing import Any

from troupe.core.client import messages as m
from troupe.core.client.dispatch import Method, Send
from troupe.core.client.session import Session
from troupe.core.messages import Message
from troupe.core.runs.perform import perform
from troupe.core.runs.queries import logs, status


async def _perform(request: Any, session: Session, send: Send) -> Message:  # noqa: ANN401
    return await perform(request, session, send)


async def _status(request: Any, session: Session, send: Send) -> Message:  # noqa: ANN401
    return await status(request, session, send)


async def _logs(request: Any, session: Session, send: Send) -> Message:  # noqa: ANN401
    return await logs(request, session, send)


def methods() -> Mapping[str, Method]:
    """The commands and queries runs offer through the client protocol, by name."""
    return {
        "perform": Method(m.PerformRequest, _perform),
        "status": Method(m.StatusRequest, _status),
        "logs": Method(m.LogsRequest, _logs),
    }
