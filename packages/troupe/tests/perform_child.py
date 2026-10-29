"""Runs perform in its own process, for tests that kill it mid-run or read its run from another
process. Arguments: the theatre's path, its isolated git environment as JSON, and the perform
request as JSON. Prints ``STARTED <run id>`` once the run's first event is recorded.

With TROUPE_TEST_STOP set in its environment, it prints ``STARTED <run id>`` at that point
instead, for tests that kill it before the run's first event (account-for-every-worktree design
D6): ``before-worktree`` blocks once the run's start is recorded and before git begins its
worktree; ``worktree-added`` blocks once git has added the worktree and before it is filled; and
``before-init`` goes on once the worktree is made and the shared state read, for a script that
hangs before its init.

An optional fourth argument names a file outside the theatre. For each segment append, the moment
it returns, a line is added to it: the wall-clock time, then the seq of each run event the append
wrote (watch-event-segments design D7: delays are timed from the write, not from the event's at).
"""

import json
import os
import re
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import troupe_store_text.store as text_store
from gitrepo import Repo
from runtesting import Harness
from troupe.core.events import EventStore
from troupe.core.messages import Message
from troupe.core.vcs import SharedState

STOP = os.environ.get("TROUPE_TEST_STOP")
BLOCK_SECONDS = 600  # far longer than any test waits: the test kills it first


class Stopping:
    """The theatre's VCS adapter, announcing the run at the point STOP names."""

    def __init__(self, inner: Any) -> None:  # noqa: ANN401
        self._inner = inner
        self._run_id = ""

    def __getattr__(self, name: str) -> Any:  # noqa: ANN401
        return getattr(self._inner, name)

    def add_worktree(self, path: Path, at: str) -> None:
        self._run_id = path.name
        if STOP == "before-worktree":
            print(f"STARTED {self._run_id}", flush=True)
            time.sleep(BLOCK_SECONDS)
        self._inner.add_worktree(path, at)
        if STOP == "worktree-added":
            print(f"STARTED {self._run_id}", flush=True)
            time.sleep(BLOCK_SECONDS)

    def shared_state(self) -> SharedState:
        state: SharedState = self._inner.shared_state()
        if STOP == "before-init" and self._run_id:
            print(f"STARTED {self._run_id}", flush=True)
            self._run_id = ""  # the second read is after the run
        return state


class Announcing(Harness):
    def event_store(self, session: Any) -> EventStore:  # noqa: ANN401
        store = super().event_store(session)
        if STOP is not None:
            store.vcs = Stopping(store.vcs)
        return store

    def send(self, update: Message) -> None:
        data: dict[str, Any] = update.to_data()
        if STOP is None and data["kind"] == "event" and data["seq"] == 0:
            print(f"STARTED {data['runId']}", flush=True)


SEQ = re.compile(rb'"seq":(\d+)')


def reported_seqs(data: bytes) -> list[int]:
    """The seq of each run event in appended lines (a line's keys are sorted, so its state, which
    holds the seq, comes before its topic)."""
    return [
        int(found.group(1))
        for line in data.splitlines()
        if b"Run.Reported" in line and (found := SEQ.search(line))
    ]


def time_appends(side: Path) -> None:
    # The store's own reference to the platform's append, replaced where the store looks it up.
    append: Callable[[Path, bytes], int] = vars(text_store)["append_bytes"]

    def timed(path: Path, data: bytes) -> int:
        result = append(path, data)
        appended = time.time()
        seqs = reported_seqs(data)
        with side.open("a", encoding="utf-8") as out:
            out.write(" ".join([repr(appended), *map(str, seqs)]) + "\n")
        return result

    vars(text_store)["append_bytes"] = timed


def main() -> None:
    path, env, request = sys.argv[1], json.loads(sys.argv[2]), json.loads(sys.argv[3])
    if len(sys.argv) > 4:
        time_appends(Path(sys.argv[4]))
    result = Announcing(Repo(Path(path), env)).perform(request)
    print(f"ENDED {result.run.outcome}", flush=True)


if __name__ == "__main__":
    main()
