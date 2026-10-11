"""File replacement and directory locks for the rest of troupe.

Thin wrappers over troupe.platform that supply the defaults from troupe.core.defaults (each can be
overridden) and turn platform failures into TroupeErrors with a code, the problem and the fix.
"""

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from troupe.core import defaults
from troupe.core.errors import BUG_REPORT_URL, TroupeError
from troupe.platform import files, locks
from troupe.platform.errors import FileInUseError, LockAlreadyHeldError, LockTimeoutError
from troupe.platform.files import WaitCallback


def replace_file(
    path: str | os.PathLike[str],
    data: bytes,
    *,
    timeout: float = defaults.REPLACE_TIMEOUT_SECONDS,
    announce_after: float = defaults.REPLACE_ANNOUNCE_AFTER_SECONDS,
    on_wait: WaitCallback | None = None,
) -> None:
    """Atomically replace the contents of ``path`` with ``data``."""
    try:
        files.replace_bytes(
            path, data, timeout=timeout, announce_after=announce_after, on_wait=on_wait
        )
    except FileInUseError as error:
        raise TroupeError(
            "replace.in-use",
            problem=(
                f"Couldn't replace the file: another program has it open "
                f"(waited {error.waited:.1f}s)."
            ),
            fix="Close the program that has the file open, such as an editor, then try again.",
            path=str(error.path),
            details={"waited_seconds": round(error.waited, 3)},
        ) from error
    except OSError as error:
        raise TroupeError(
            "replace.failed",
            problem=f"Couldn't write the file: {error.strerror or error}.",
            fix="Check that the file and its directory are writable, then try again.",
            path=str(Path(path).absolute()),
        ) from error


def read_file(
    path: str | os.PathLike[str],
    *,
    timeout: float = defaults.REPLACE_TIMEOUT_SECONDS,
    announce_after: float = defaults.REPLACE_ANNOUNCE_AFTER_SECONDS,
    on_wait: WaitCallback | None = None,
) -> bytes:
    """Read the whole of ``path``, as one complete version even while it is being replaced."""
    try:
        return files.read_bytes(
            path, timeout=timeout, announce_after=announce_after, on_wait=on_wait
        )
    except FileInUseError as error:
        raise TroupeError(
            "replace.in-use",
            problem=(
                f"Couldn't read the file: another program is holding it "
                f"(waited {error.waited:.1f}s)."
            ),
            fix="Close the program that has the file open, such as an editor, then try again.",
            path=str(error.path),
            details={"waited_seconds": round(error.waited, 3)},
        ) from error


@contextmanager
def directory_lock(
    directory: str | os.PathLike[str],
    *,
    timeout: float = defaults.LOCK_TIMEOUT_SECONDS,
    announce_after: float = defaults.LOCK_ANNOUNCE_AFTER_SECONDS,
    on_wait: WaitCallback | None = None,
) -> Iterator[Path]:
    """Hold the exclusive lock on ``directory`` for the duration of the ``with`` block."""
    try:
        with locks.hold(
            directory, timeout=timeout, announce_after=announce_after, on_wait=on_wait
        ) as lock_path:
            yield lock_path
    except LockTimeoutError as error:
        raise TroupeError(
            "lock.timeout",
            problem=f"Timed out after {error.waited:.1f}s waiting for another troupe process.",
            fix="Another troupe command is using this directory. Let it finish, then try again.",
            path=str(error.lock_path.absolute()),
            details={"waited_seconds": round(error.waited, 3)},
        ) from error
    except LockAlreadyHeldError as error:
        raise TroupeError(
            "lock.already-held",
            problem="This command already holds this lock; taking it again would deadlock.",
            fix=f"This is a bug in troupe. Please report it, with the command you ran, at "
            f"{BUG_REPORT_URL}",
            path=str(error.lock_path.absolute()),
        ) from error
