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
from troupe.core.events import EventStore
from troupe.core.messages import Message
from troupe.core.runners.limits import RunLimits
from troupe.core.runs.perform import Backends, perform

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


@dataclass
class Harness:
    """perform, run in process against a real git theatre."""

    repo: Repo
    env: dict[str, str] = field(default_factory=lambda: {**ADA, **ALLOW})
    limits: RunLimits = LIMITS
    store_wrapper: Callable[[EventStore], EventStore] | None = None
    identity_chain: tuple[str, ...] | None = None
    cancel: CancelSignal = field(default_factory=CancelSignal)
    updates: list[dict[str, Any]] = field(default_factory=list)
    stores: list[EventStore] = field(default_factory=list)

    def session(self) -> Session:
        return Session(theatre=self.repo.path, env=self.env, cancel=self.cancel)

    def event_store(self, _: Session) -> EventStore:
        store = git_service(self.repo, env=self.env)
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

    def perform(self, request: dict[str, Any]) -> m.PerformResult:
        parsed = m.PerformRequest.from_data(request)
        return asyncio.run(perform(parsed, self.session(), self.send, backends=self.backends()))


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
