"""Helpers for runs' tests: a git theatre, a session that may run on the local stage, and perform
called in process with the scripted runner (perform-status-logs)."""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from gitrepo import Repo, make_repo
from storetesting import git_service
from troupe.core.artifacts import load_store
from troupe.core.client import messages as m
from troupe.core.client.session import CancelSignal, Session
from troupe.core.config.changes import change
from troupe.core.config.stream import read as read_config
from troupe.core.config.stream import record as record_config
from troupe.core.errors import TroupeError
from troupe.core.events import EventStore
from troupe.core.messages import Message
from troupe.core.runners.limits import RunLimits
from troupe.core.runs.perform import Backends, perform
from troupe.core.runs.queries import logs, status

ALLOW = {"TROUPE_POLICY_ALLOW_UNENFORCED_LOCAL_STAGE": "true"}
ADA = {"TROUPE_ACTOR": "human:ada@example.com"}
LIMITS = RunLimits(start_timeout=10.0, cancel_grace=2.0, run_timeout=20.0, silence_announce=10.0)
INIT = {"event": {"type": "init", "runner": {"name": "scripted", "version": "0.1.0"}, "tools": []}}
OK = {"event": {"type": "result", "status": "ok", "message": "done"}}


def turn(text: str) -> dict[str, Any]:
    return {"event": {"type": "turn", "role": "assistant", "text": text}}


def script(*steps: dict[str, Any], on_cancel: str = "honour") -> dict[str, Any]:
    return {"script": {"onCancel": on_cancel, "steps": list(steps)}}


def theatre(root: Path) -> Repo:
    repo = make_repo(root)
    (repo.path / ".troupe").mkdir()
    return repo


@dataclass(frozen=True)
class Performed:
    """A perform's run, for tests that ran one (not a rehearsal)."""

    run: m.RunSummary


@dataclass
class Harness:
    """perform, run in process against a real git theatre."""

    repo: Repo
    env: dict[str, str] = field(default_factory=lambda: {**ADA, **ALLOW})
    limits: RunLimits = LIMITS
    store_wrapper: Callable[[EventStore], EventStore] | None = None
    store_options: dict[str, Any] = field(default_factory=dict)
    identity_chain: tuple[str, ...] | None = None
    cancel: CancelSignal = field(default_factory=CancelSignal)
    updates: list[dict[str, Any]] = field(default_factory=list)
    stores: list[EventStore] = field(default_factory=list)

    def session(self) -> Session:
        return Session(theatre=self.repo.path, env=self.env, cancel=self.cancel)

    def event_store(self, _: Session) -> EventStore:
        store = git_service(self.repo, env=self.env, **self.store_options)
        if self.identity_chain is not None:
            store.identity_chain = self.identity_chain
        store = self.store_wrapper(store) if self.store_wrapper else store
        self.stores.append(store)
        return store

    def backends(self) -> Backends:
        return Backends(
            event_store=self.event_store,
            artifact_store=lambda s: load_store(
                "local", s.theatre / ".troupe" / "local" / "artifacts"
            ),
            limits=self.limits,
        )

    def send(self, update: Message) -> None:
        self.updates.append(update.to_data())

    def configure(self, request: dict[str, Any]) -> None:
        """Define the actor ``request`` names in config, as the old perform request described
        it: its runner, options and effect check (config-model design D14)."""
        check = request.get("effectCheck", {"kind": "none"})
        actor: dict[str, Any] = {
            "runner": request.get("runner", "scripted"),
            "options": request.get("options", {}),
            "expect": list(check.get("paths", [])),
        }
        if "character" in request:
            actor["character"] = request["character"]
        store = git_service(self.repo, env={**ADA, **self.env})
        merged = read_config(store)
        entries = change(merged.config, [(["actors", request["actor"]], actor)])
        if entries:
            record_config(store.command(via="cli"), merged, entries, [])

    def perform(self, request: dict[str, Any]) -> "Performed":
        """Configure the actor, then perform it: the run, as perform's result names it."""
        self.configure(request)
        asked = {k: request[k] for k in ("actor", "direction", "rehearse") if k in request}
        parsed = m.PerformRequest.from_data(asked)
        result = asyncio.run(perform(parsed, self.session(), self.send, backends=self.backends()))
        assert result.run is not None, "a rehearsal: use perform_result"
        return Performed(result.run)

    def perform_result(self, request: dict[str, Any]) -> m.PerformResult:
        """Configure the actor, then perform it, returning perform's whole result."""
        self.configure(request)
        asked = {k: request[k] for k in ("actor", "direction", "rehearse") if k in request}
        parsed = m.PerformRequest.from_data(asked)
        return asyncio.run(perform(parsed, self.session(), self.send, backends=self.backends()))

    def status(self, **fields: Any) -> m.StatusResult:  # noqa: ANN401
        parsed = m.StatusRequest.from_data(fields)
        return asyncio.run(status(parsed, self.session(), self.send, backends=self.backends()))

    def logs(self, **fields: Any) -> m.LogsResult:  # noqa: ANN401
        parsed = m.LogsRequest.from_data(fields)
        return asyncio.run(logs(parsed, self.session(), self.send, backends=self.backends()))


def request(
    options: dict[str, Any],
    *,
    effect: dict[str, Any] | None = None,
    **fields: Any,  # noqa: ANN401
) -> dict[str, Any]:
    return {
        "actor": "tester",
        "runner": "scripted",
        "options": options,
        "effectCheck": effect or {"kind": "none"},
        **fields,
    }


def failing_at(reported: int, *, end_too: bool = False) -> Any:  # noqa: ANN401
    """A store wrapper whose write of the given run event (by seq), and of the end if asked,
    fails as a full disk would."""

    def wrap(store: Any) -> Any:  # noqa: ANN401
        original = store.record_with_lineage

        def record(events: Any, lineage: Any, **kwargs: Any) -> Any:  # noqa: ANN401
            for event in events:
                name = type(event).__qualname__
                if (name == "Run.Reported" and event.seq == reported) or (
                    end_too and name == "Run.Ended"
                ):
                    raise TroupeError(
                        "artifact.write-failed",
                        problem="No space left on device.",
                        fix="Free some.",
                    )
            return original(events, lineage, **kwargs)

        store.record_with_lineage = record
        return store

    return wrap
