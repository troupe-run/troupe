"""Helpers that test_run_workspaces.py shares with other test modules."""

import json
from typing import Any
from uuid import UUID

from runtesting import (
    Harness,
    request,
    script,
)
from troupe.core.errors import TroupeError
from troupe.core.events import EventStore
from troupe.core.vcs import Vcs
from troupe_plugin_sdk.messages import Message


def write(path: str, content: str) -> dict[str, Any]:
    return {"writeFile": {"path": path, "content": content}}


def worktree_request(*steps: dict[str, Any], **fields: Any) -> dict[str, Any]:  # noqa: ANN401
    return request(script(*steps), workspace="worktree", **fields)


class Recording(Harness):
    """A harness that runs ``on_running`` when the runner's first event arrives: its worktree is
    made and the shared state read, so what it does counts as done during the run."""

    on_running: Any = None

    def send(self, update: Message) -> None:
        super().send(update)
        data = update.to_data()
        if data.get("kind") == "event" and data["seq"] == 0 and self.on_running is not None:
            self.on_running()


def configured(made: Harness, *steps: dict[str, Any], **fields: Any) -> dict[str, Any]:  # noqa: ANN401
    """Configure the actor and commit it, so the theatre's HEAD holds its config."""
    asked = worktree_request(*steps, **fields)
    made.configure(asked)
    made.repo.commit_all("config")
    return asked


def history(made: Harness, run_id: str) -> list[dict[str, Any]]:
    return [json.loads(event.state) for event in made.stores[-1].history(UUID(run_id))]


# Requirement: A worktree is made only after every check passes


class _Wrapped:
    """A VCS adapter with one operation replaced."""

    def __init__(self, inner: Vcs, name: str, replacement: Any) -> None:  # noqa: ANN401
        self._inner, self._name, self._replacement = inner, name, replacement

    def __getattr__(self, name: str) -> Any:  # noqa: ANN401
        return self._replacement if name == self._name else getattr(self._inner, name)


def _replacing(name: str, replacement: Any) -> Any:  # noqa: ANN401
    def wrap(store: EventStore) -> EventStore:
        store.vcs = _Wrapped(store.vcs, name, replacement)
        return store

    return wrap


def _vcs_failed(*_: object) -> Any:  # noqa: ANN401
    raise TroupeError(
        "vcs.failed",
        problem="git checkout-index failed",
        fix="f",
        details={"command": "git checkout-index", "exitStatus": 128},
    )
