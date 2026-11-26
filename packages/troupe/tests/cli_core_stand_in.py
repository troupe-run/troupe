"""A stand-in core for running troupe's commands in-process in a unit test (unit-tests-cli-commands-
config-init design D1-D4).

The core's handlers need a git theatre, which a unit test can't use. ``StandIn`` replaces the one
name between the CLI and the core, ``troupe.cli.commands.call``, with the real dispatcher bound to
stand-in methods: each keeps its method's real request class, so the dispatcher still parses every
request strictly, and returns the result and sends the updates the test gives it, which are the
protocol's own messages. It records each call's method, request and session.

A stand-in can press Ctrl-C during its call: it calls the SIGINT handler the CLI installed, as a
signal would, without sending one (design D3).
"""

import asyncio
import functools
import io
import signal
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from troupe.cli import commands as cli_commands
from troupe.cli import main
from troupe.core.client import dispatch
from troupe.core.client.session import Session
from troupe.core.exit_codes import ExitCode
from troupe.core.theatre import THEATRE_DIR
from troupe.platform.interrupts import INTERRUPTS
from troupe_plugin_sdk.messages import Message


@dataclass(frozen=True)
class Call:
    """One call the CLI made to the core."""

    method: str
    request: dict[str, Any]
    """The request as the dispatcher parsed it, back as data."""
    session: Session


@dataclass
class Reply:
    """What the core does for one method: send ``updates``, press Ctrl-C ``presses`` times after
    them, then return ``result``."""

    result: Message
    updates: Sequence[Message] = ()
    presses: int = 0


@dataclass(frozen=True)
class Ran:
    """What a command did: its exit code and what it printed on each stream."""

    code: ExitCode
    stdout: str
    stderr: str

    @property
    def out(self) -> list[str]:
        return self.stdout.splitlines()

    @property
    def err(self) -> list[str]:
        return self.stderr.splitlines()


@dataclass
class StandIn:
    """The core, standing in: ``replies`` by method, and the ``calls`` made so far."""

    theatre: Path
    replies: dict[str, Reply] = field(default_factory=dict)
    calls: list[Call] = field(default_factory=list)

    def reply(self, method: str, result: Message, *updates: Message, presses: int = 0) -> None:
        self.replies[method] = Reply(result, updates, presses)

    def run(self, *argv: str) -> Ran:
        stdout, stderr = io.StringIO(), io.StringIO()
        handlers = {each: signal.getsignal(each) for each in INTERRUPTS}
        try:
            code = main(list(argv), stdout=stdout, stderr=stderr)
        finally:  # however the command's code is changed, Ctrl-C works after it as before
            for each, handler in handlers.items():
                signal.signal(each, handler)
        return Ran(code, stdout.getvalue(), stderr.getvalue())

    @property
    def requests(self) -> list[tuple[str, dict[str, Any]]]:
        return [(each.method, each.request) for each in self.calls]

    def _methods(self) -> dict[str, dispatch.Method]:
        real = dispatch.handlers()

        def method(name: str) -> dispatch.Method:
            async def handler(request: Message, session: Session, send: dispatch.Send) -> Message:
                self.calls.append(Call(name, request.to_data(), session))
                reply = self.replies[name]
                for update in reply.updates:
                    send(update)
                for _ in range(reply.presses):
                    press_ctrl_c()
                    await asyncio.sleep(0)  # the CLI's handler hands over to the loop
                return reply.result

            return dispatch.Method(real[name].request, handler)

        return {name: method(name) for name in real}


def press_ctrl_c() -> None:
    """What a Ctrl-C does: call the SIGINT handler that's installed, as the signal would."""
    handler = signal.getsignal(signal.SIGINT)
    assert callable(handler), "nothing is catching Ctrl-C"
    handler(signal.SIGINT, None)


def stand_in(monkeypatch: pytest.MonkeyPatch, directory: Path, *, theatre: bool = True) -> StandIn:
    """A stand-in core for commands run in ``directory``, made a theatre unless ``theatre`` is
    False (as for init, which makes one)."""
    if theatre:
        (directory / THEATRE_DIR).mkdir()
    monkeypatch.chdir(directory)
    core = StandIn(directory)
    monkeypatch.setattr(
        cli_commands, "call", functools.partial(dispatch.call, methods=core._methods())
    )
    return core
