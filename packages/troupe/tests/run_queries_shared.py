"""Helpers that test_run_queries.py shares with other test modules."""

import contextlib
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from gitrepo import Repo
from runtesting import request
from storetesting import (
    wait_until,
)
from troupe.core.events import EventStore
from troupe.core.runs.aggregate import Run
from troupe.platform.processes import is_running

CHILD = Path(__file__).with_name("perform_child.py")
STAGE = {
    "name": "local",
    "effects": "unenforced",
    "allowedBy": {"setting": "allow_unenforced_local_stage", "source": "env"},
}


class Child:
    """perform running in another process."""

    def __init__(
        self,
        repo: Repo,
        options: dict[str, Any],
        *,
        appends: Path | None = None,
        shown: Path | None = None,
        stop: str | None = None,
        silence: float | None = None,
        **fields: Any,  # noqa: ANN401
    ) -> None:
        """``appends``: a file outside the theatre where the child notes when each segment
        append returned, and the run events it wrote. ``shown``: a file outside the theatre
        where the test lists each seq its follower has shown, and the child waits for each before
        recording the next (windows-follow-flake design D5). ``stop``: where the child announces the
        run instead of at its first event, and ``fields``: more of the request, such as its
        workspace (perform_child.py). ``silence``: the seconds after which its run announces a
        silence."""
        self.process = subprocess.Popen(
            [
                sys.executable,
                str(CHILD),
                str(repo.path),
                json.dumps(repo.env),
                json.dumps(request(options, **fields)),
                *([str(appends)] if appends is not None else []),
            ],
            stdout=subprocess.PIPE,
            text=True,
            env={
                **os.environ,
                **({"TROUPE_TEST_STOP": stop} if stop is not None else {}),
                **({"TROUPE_TEST_SHOWN": str(shown)} if shown is not None else {}),
                **({"TROUPE_TEST_SILENCE_SECONDS": str(silence)} if silence is not None else {}),
            },
        )
        assert self.process.stdout is not None
        line = self.process.stdout.readline().split()
        assert line[:1] == ["STARTED"], line
        assert len(line) == 3, line
        self.run_id = line[1]
        self.pid = int(line[2])
        """The process running perform, which on Windows isn't ``self.process`` when that is the
        venv's python.exe: a launcher, whose child is the interpreter (#405)."""
        self.killed_in: float | None = None
        """Seconds from the kill until perform's own process had ended, once killed."""

    def kill(self) -> None:
        """Kill perform, and return once its own process has ended. Waiting on the process this
        started isn't enough on Windows: the launcher ends first, and perform, ended by the
        launcher's job a moment later, still holds its run's lease until it has (#405)."""
        started = time.monotonic()
        self.process.kill()
        self.process.wait(timeout=30)
        if is_running(self.pid):
            # The launcher's job normally ends it. If not, end it here: nothing should depend on
            # how the launcher is built. OSError: it ended between the look and the kill.
            with contextlib.suppress(OSError):
                os.kill(self.pid, signal.SIGTERM)
        wait_until(lambda: not is_running(self.pid), f"perform's process {self.pid} to end")
        self.killed_in = time.monotonic() - started

    def finish(self) -> str:
        assert self.process.stdout is not None
        out, _ = self.process.communicate(timeout=60)
        return out


def started(store: EventStore, workspace: dict[str, Any]) -> Run:
    """A run's start as perform records it."""
    run = Run(
        run_id="6f1d2c3b-0000-4000-8000-000000000002",
        actor="tester",
        runner_requested="scripted",
        stage=STAGE,
        effect_check={"kind": "none"},
        direction="sha256:" + "a" * 64,
        config=["sha256:" + "b" * 64],
        workspace=workspace,
        on_context_full={"value": "fail", "source": "default"},
    )
    store.command(via="cli").record(run.collect_events())
    return run
