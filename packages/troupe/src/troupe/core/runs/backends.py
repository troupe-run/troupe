"""Where runs are recorded and kept, shared by perform, the queries and the changes (spec: runs;
perform-status-logs design D11).

It lives apart from troupe.core.runs.perform so that ``troupe status``, ``logs``, ``diff``,
``accept`` and ``discard`` don't load what only a perform needs: config projection's YAML, the
runner table's schema checking and the runner host (cli-starts-fast design D5).
"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from troupe.core.artifacts import ArtifactStore
from troupe.core.client.session import Session
from troupe.core.events import EventStore
from troupe.core.runners.limits import RunLimits
from troupe.core.stores import local_dir, open_artifact_store, open_event_store


def lease_dir(theatre: Path, run_id: str) -> Path:
    """Where a run's lease is held while its perform is alive (design D11)."""
    return local_dir(theatre) / "runs" / run_id


PERFORM_PID_FILE = "perform.pid"
"""In a run's lease directory: the id of the process running its perform, written once it holds
the lease, so a lease still held after that process has ended reads as interrupted
(run-test-timing design D4)."""


@dataclass(frozen=True)
class Backends:
    """Where runs are recorded and kept, and the limits they run under. Tests replace these."""

    event_store: Callable[[Session], EventStore] = open_event_store
    artifact_store: Callable[[Session], ArtifactStore] = open_artifact_store
    limits: RunLimits | None = None
