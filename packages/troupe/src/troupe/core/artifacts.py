"""Content-addressed artifacts (spec: artifact-store; runner-contract design D10).

Run artifacts too large or too sensitive for git, such as raw transcripts, are stored by the
SHA-256 of their bytes and referenced as ``sha256:<hex>``. Lineage keeps the reference, so any
copy can be verified (decision #4). ArtifactStore is the port; LocalArtifactStore keeps artifacts
in a directory, and MemoryArtifactStore keeps them in memory for tests.
"""

import contextlib
import hashlib
import os
import re
import tempfile
from pathlib import Path
from types import TracebackType
from typing import Protocol, Self

from troupe.core import defaults
from troupe.core.errors import TroupeError
from troupe.core.files import read_file
from troupe.platform import files
from troupe.platform.errors import FileInUseError

PREFIX = "sha256:"
REF_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")

GITIGNORE = b"# Written by troupe: this directory is a local artifact store, kept out of git.\n*\n"


def reference(data: bytes) -> str:
    """The reference for ``data``: ``sha256:`` and the hex SHA-256 of its bytes."""
    return PREFIX + hashlib.sha256(data).hexdigest()


def _digest(ref: str) -> str:
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


class _WriterBase:
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


def _missing(ref: str, path: Path | None) -> TroupeError:
    return TroupeError(
        "artifact.missing",
        problem=f"The artifact {ref} isn't in this store.",
        fix="Check that the reference came from this theatre's store, or copy the artifact into it "
        "from wherever it was kept.",
        path=None if path is None else str(path.absolute()),
        details={"ref": ref},
    )


class LocalArtifactStore:
    """Artifacts as files under ``root``: ``sha256/<first two hex digits>/<hex>``.

    The directory keeps itself out of git with its own ``.gitignore``, so no file of the user's is
    ever edited for it. Writers stream into ``tmp/`` and move the finished file into place.
    """

    def __init__(self, root: str | os.PathLike[str]) -> None:
        self.root = Path(root)

    def _prepare(self) -> None:
        try:
            (self.root / "sha256").mkdir(parents=True, exist_ok=True)
            (self.root / "tmp").mkdir(exist_ok=True)
            ignore = self.root / ".gitignore"
            if not ignore.exists():
                files.replace_bytes(
                    ignore,
                    GITIGNORE,
                    timeout=defaults.REPLACE_TIMEOUT_SECONDS,
                    announce_after=defaults.REPLACE_ANNOUNCE_AFTER_SECONDS,
                )
        except (OSError, FileInUseError) as error:
            raise _write_failed(self.root, error) from error

    def path_for(self, ref: str) -> Path:
        digest = _digest(ref)
        return self.root / "sha256" / digest[:2] / digest

    def open_writer(self) -> "LocalArtifactWriter":
        self._prepare()
        return LocalArtifactWriter(self)

    def put(self, data: bytes) -> str:
        with self.open_writer() as writer:
            writer.write(data)
            return writer.finish()

    def contains(self, ref: str) -> bool:
        return self.path_for(ref).is_file()

    def read(self, ref: str) -> bytes:
        path = self.path_for(ref)
        if not path.is_file():
            raise _missing(ref, path)
        data = read_file(path)
        if reference(data) != ref:
            raise TroupeError(
                "artifact.corrupt",
                problem=f"The stored artifact {ref} has changed since it was stored: its bytes no "
                "longer match its hash.",
                fix="Restore the file from another copy of the artifact, or remove it so the run's "
                "record shows it as missing rather than wrong.",
                path=str(path.absolute()),
                details={"ref": ref, "actual": reference(data)},
            )
        return data


def _write_failed(path: Path, error: BaseException) -> TroupeError:
    reason = error.strerror if isinstance(error, OSError) and error.strerror else str(error)
    return TroupeError(
        "artifact.write-failed",
        problem=f"Couldn't store an artifact: {reason}.",
        fix="Check that the artifact store's directory is writable and its disk isn't full, then "
        "try again.",
        path=str(path.absolute()),
    )


class LocalArtifactWriter(_WriterBase):
    def __init__(self, store: LocalArtifactStore) -> None:
        self._store = store
        self._hash = hashlib.sha256()
        fd, name = tempfile.mkstemp(dir=store.root / "tmp", prefix="artifact-", suffix=".part")
        self._temp = Path(name)
        self._file = os.fdopen(fd, "wb")
        self._done = False

    def write(self, data: bytes) -> None:
        if self._done:
            raise ValueError("this artifact writer has already finished")
        try:
            self._file.write(data)
        except OSError as error:
            self.abort()
            raise _write_failed(self._store.root, error) from error
        self._hash.update(data)

    def finish(self) -> str:
        if self._done:
            raise ValueError("this artifact writer has already finished")
        ref = PREFIX + self._hash.hexdigest()
        target = self._store.path_for(ref)
        try:
            self._file.flush()
            os.fsync(self._file.fileno())
            self._file.close()
            target.parent.mkdir(exist_ok=True)
            files.commit_file(
                self._temp,
                target,
                timeout=defaults.REPLACE_TIMEOUT_SECONDS,
                announce_after=defaults.REPLACE_ANNOUNCE_AFTER_SECONDS,
            )
        except (OSError, FileInUseError) as error:
            self.abort()
            raise _write_failed(target, error) from error
        self._done = True
        return ref

    def abort(self) -> None:
        if self._done:
            return
        self._done = True
        with contextlib.suppress(OSError):
            self._file.close()
        with contextlib.suppress(FileNotFoundError):
            self._temp.unlink()


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
        _digest(ref)
        return ref in self.artifacts

    def read(self, ref: str) -> bytes:
        _digest(ref)
        if ref not in self.artifacts:
            raise _missing(ref, None)
        return self.artifacts[ref]


class MemoryArtifactWriter(_WriterBase):
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
