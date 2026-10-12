"""Content-addressed artifacts (spec: artifact-store; runner-contract design D10).

Run artifacts too large or too sensitive for git, such as raw transcripts, are stored by the
SHA-256 of their bytes and referenced as ``sha256:<hex>``. Lineage keeps the reference, so any
copy can be verified (decision #4). ArtifactStore is the port. MemoryArtifactStore keeps artifacts
in memory, for tests and for callers that keep nothing; other stores are separately packaged and
found by name through the ``troupe.artifacts`` entry point group (load_store).
"""

import hashlib
import importlib.metadata
import os
import re
from pathlib import Path
from types import TracebackType
from typing import Protocol, Self

from troupe.core.errors import TroupeError

PREFIX = "sha256:"
REF_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")


def reference(data: bytes) -> str:
    """The reference for ``data``: ``sha256:`` and the hex SHA-256 of its bytes."""
    return PREFIX + hashlib.sha256(data).hexdigest()


def digest_of(ref: str) -> str:
    if not REF_PATTERN.match(ref):
        msg = f"not an artifact reference: {ref!r} (expected sha256: and 64 lowercase hex digits)"
        raise ValueError(msg)
    return ref.removeprefix(PREFIX)


class ArtifactWriter(Protocol):
    """Writes one artifact in pieces. Readable only once finished."""

    def write(self, data: bytes) -> None: ...

    def finish(self) -> str:
        """Complete the artifact and return its reference."""
        ...

    def abort(self) -> None:
        """Abandon the artifact. Safe to call after finish or abort."""
        ...

    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...


class ArtifactStore(Protocol):
    """Where run artifacts are kept. Callers depend only on this interface."""

    def open_writer(self) -> ArtifactWriter: ...

    def put(self, data: bytes) -> str:
        """Store ``data`` whole and return its reference."""
        ...

    def read(self, ref: str) -> bytes:
        """The artifact's bytes, verified against ``ref``."""
        ...

    def contains(self, ref: str) -> bool: ...


class WriterBase:
    """Shared context-manager behaviour: an exception inside ``with`` abandons the artifact."""

    def abort(self) -> None:
        raise NotImplementedError

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.abort()  # after finish this does nothing; otherwise the artifact is abandoned


def missing_error(ref: str, path: Path | None) -> TroupeError:
    return TroupeError(
        "artifact.missing",
        problem=f"The artifact {ref} isn't in this store.",
        fix="Check that the reference came from this theatre's store, or copy the artifact into it "
        "from wherever it was kept.",
        path=None if path is None else str(path.absolute()),
        details={"ref": ref},
    )


def write_failed_error(path: Path, error: BaseException) -> TroupeError:
    reason = error.strerror if isinstance(error, OSError) and error.strerror else str(error)
    return TroupeError(
        "artifact.write-failed",
        problem=f"Couldn't store an artifact: {reason}.",
        fix="Check that the artifact store's directory is writable and its disk isn't full, then "
        "try again.",
        path=str(path.absolute()),
    )


class MemoryArtifactStore:
    """Artifacts in memory, for tests and for callers that keep nothing."""

    def __init__(self) -> None:
        self.artifacts: dict[str, bytes] = {}

    def open_writer(self) -> "MemoryArtifactWriter":
        return MemoryArtifactWriter(self)

    def put(self, data: bytes) -> str:
        ref = reference(data)
        self.artifacts[ref] = bytes(data)
        return ref

    def contains(self, ref: str) -> bool:
        digest_of(ref)
        return ref in self.artifacts

    def read(self, ref: str) -> bytes:
        digest_of(ref)
        if ref not in self.artifacts:
            raise missing_error(ref, None)
        return self.artifacts[ref]


class MemoryArtifactWriter(WriterBase):
    def __init__(self, store: MemoryArtifactStore) -> None:
        self._store = store
        self._parts: list[bytes] = []
        self._done = False

    def write(self, data: bytes) -> None:
        if self._done:
            raise ValueError("this artifact writer has already finished")
        self._parts.append(bytes(data))

    def finish(self) -> str:
        if self._done:
            raise ValueError("this artifact writer has already finished")
        self._done = True
        return self._store.put(b"".join(self._parts))

    def abort(self) -> None:
        self._done = True
        self._parts.clear()


ENTRY_POINT_GROUP = "troupe.artifacts"


def installed_stores() -> dict[str, "importlib.metadata.EntryPoint"]:
    """The artifact stores installed, by name."""
    return {entry.name: entry for entry in importlib.metadata.entry_points(group=ENTRY_POINT_GROUP)}


def load_store(name: str, root: str | os.PathLike[str]) -> ArtifactStore:
    """The artifact store registered as ``name``, keeping its artifacts under ``root``."""
    stores = installed_stores()
    if name not in stores:
        installed = ", ".join(sorted(stores)) or "none"
        raise TroupeError(
            "artifact.unknown-store",
            problem=f"No artifact store named {name!r} is installed (installed: {installed}).",
            fix="Use one of the installed stores, or install the package that provides this one.",
            details={"store": name, "installed": sorted(stores)},
        )
    factory = stores[name].load()
    store: ArtifactStore = factory(Path(root))
    return store
