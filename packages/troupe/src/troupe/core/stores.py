"""Opening a session's event store and artifact store (perform-status-logs design D1).

Runs and config both record in the theatre's event store, so how a session opens it is decided
here, once: by name from troupe.core.defaults, with the session's environment and clock.
"""

from pathlib import Path

from troupe.core import defaults
from troupe.core.artifacts import ArtifactStore, load_store
from troupe.core.client.session import Session
from troupe.core.events import EventStore


def local_dir(theatre: Path) -> Path:
    """The theatre's own local state, never committed."""
    return theatre / ".troupe" / "local"


def open_event_store(session: Session) -> EventStore:
    return EventStore.open(
        session.theatre,
        vcs=defaults.VCS,
        store=defaults.EVENT_STORE,
        env=session.env,
        clock=session.clock,
    )


def open_artifact_store(session: Session) -> ArtifactStore:
    return load_store(defaults.ARTIFACT_STORE, local_dir(session.theatre) / "artifacts")
