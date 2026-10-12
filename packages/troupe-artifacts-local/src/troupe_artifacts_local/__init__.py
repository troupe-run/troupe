"""troupe's local artifact store (spec: artifact-store; runner-contract design D10).

Artifacts are files under the root directory its caller gives, at
``sha256/<first two hex digits>/<hex>``. Writers stream into ``tmp/`` and move the finished file
into place. The directory also keeps itself out of git with its own ``.gitignore``, a guard for a
root put outside ``.troupe/local/``.
"""

import contextlib
import hashlib
import os
import tempfile
from pathlib import Path

from troupe.core import defaults
from troupe.core.artifacts import (
    PREFIX,
    WriterBase,
    digest_of,
    missing_error,
    reference,
    write_failed_error,
)
from troupe.core.errors import TroupeError
from troupe.core.files import read_file
from troupe.platform import files
from troupe.platform.errors import FileInUseError

GITIGNORE = b"# Written by troupe: this directory is a local artifact store, kept out of git.\n*\n"


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
            raise write_failed_error(self.root, error) from error

    def path_for(self, ref: str) -> Path:
        digest = digest_of(ref)
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
            raise missing_error(ref, path)
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


class LocalArtifactWriter(WriterBase):
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
            raise write_failed_error(self._store.root, error) from error
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
            raise write_failed_error(target, error) from error
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
