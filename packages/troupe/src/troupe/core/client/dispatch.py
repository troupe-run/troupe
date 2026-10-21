"""The dispatcher: every surface's one way into the core's commands and queries (spec:
client-protocol; perform-status-logs design D2).

``call`` takes a method's name and its request as data, parses the request strictly before
anything runs, and calls the method's handler with the parsed request, the session, and a way to
send updates. Updates and the result go back as data, in their schemas' shapes. A request the
protocol refuses is client.invalid-request (or client.unknown-method), naming what was wrong; a
call that can't complete raises its TroupeError.
"""

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

from troupe.core.client.session import Session
from troupe.core.errors import TroupeError
from troupe.core.messages import Message, ProtocolError

UpdateCallback = Callable[[dict[str, Any]], None]
"""Receives each update, as data, in the order it happens."""

Send = Callable[[Message], None]
"""How a handler sends an update."""

Handler = Callable[[Any, Session, Send], Awaitable[Message]]


@dataclass(frozen=True)
class Method:
    """A command or query: its request type, and the handler that runs it."""

    request: type[Message]
    handler: Handler


def handlers() -> Mapping[str, Method]:
    """Every method the core offers, by name."""
    # Imported here: troupe.core.runs builds its Methods from this module, so a top-level import
    # would be circular.
    from troupe.core.config.commands import methods as config_methods
    from troupe.core.runs import methods as run_methods

    return {**run_methods(), **config_methods()}


async def call(
    method: str,
    params: object,
    session: Session,
    on_update: UpdateCallback | None = None,
    *,
    methods: Mapping[str, Method] | None = None,
) -> dict[str, Any]:
    """Run ``method`` with the request ``params`` in ``session``; return its result as data."""
    table = handlers() if methods is None else methods
    if method not in table:
        known = ", ".join(sorted(table))
        raise TroupeError(
            "client.unknown-method",
            problem=f"{method!r} isn't a command or query troupe offers (it offers: {known}).",
            fix=f"Call one of: {known}.",
            details={"method": method, "known": sorted(table)},
        )
    entry = table[method]
    try:
        request = entry.request.from_data(params)
    except ProtocolError as error:
        raise TroupeError(
            "client.invalid-request",
            problem=f"The {method} request isn't valid: {error}.",
            fix=f"Send a {method} request that matches protocol/schemas/client/"
            f"{method}-request.schema.json.",
            details={"method": method, "reason": str(error)},
        ) from error

    def send(update: Message) -> None:
        if on_update is not None:
            on_update(update.to_data())

    result = await entry.handler(request, session, send)
    return result.to_data()
