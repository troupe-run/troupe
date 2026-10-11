"""Directory locks (spec: platform; design D6).

One mechanism on every platform: an OS-level exclusive lock on an empty lock file inside the
directory being protected (``<directory>/.lock``). POSIX uses ``fcntl.flock``; Windows uses
``msvcrt.locking`` on the first byte. The OS releases the lock if the holder exits or crashes, so
there is never a stale lock to clean up. The file is created when missing and never deleted, since
deleting it would race with another process waiting on it.

Waiting is bounded and announced: the waiter polls, reports through ``on_wait`` once
``announce_after`` has passed, and raises LockTimeoutError after ``timeout``. Taking a lock
this process already holds raises LockAlreadyHeldError at once, rather than deadlocking.
"""

import os
import sys
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from troupe.platform.errors import LockAlreadyHeldError, LockTimeoutError
from troupe.platform.files import WaitCallback

LOCK_FILE_NAME = ".lock"

_held: set[tuple[int, int]] = set()
_held_guard = threading.Lock()

if sys.platform == "win32":
    import msvcrt

    def _try_lock(fd: int) -> bool:
        os.lseek(fd, 0, os.SEEK_SET)
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
        return True

    def _unlock(fd: int) -> None:
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)

else:
    import fcntl

    def _try_lock(fd: int) -> bool:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        return True

    def _unlock(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_UN)


@contextmanager
def hold(
    directory: str | os.PathLike[str],
    *,
    timeout: float,
    announce_after: float,
    on_wait: WaitCallback | None = None,
) -> Iterator[Path]:
    """Hold the exclusive lock on ``directory`` for the duration of the ``with`` block."""
    lock_path = Path(directory) / LOCK_FILE_NAME
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        info = os.fstat(fd)
        key = (info.st_dev, info.st_ino)
        with _held_guard:
            if key in _held:
                raise LockAlreadyHeldError(lock_path)
            _held.add(key)
        try:
            _acquire(fd, lock_path, timeout=timeout, announce_after=announce_after, on_wait=on_wait)
            try:
                yield lock_path
            finally:
                _unlock(fd)
        finally:
            with _held_guard:
                _held.discard(key)
    finally:
        os.close(fd)


def _acquire(
    fd: int,
    lock_path: Path,
    *,
    timeout: float,
    announce_after: float,
    on_wait: WaitCallback | None,
) -> None:
    started = time.monotonic()
    delay = 0.02
    announced = False
    while not _try_lock(fd):
        waited = time.monotonic() - started
        if waited >= timeout:
            raise LockTimeoutError(lock_path, waited)
        if not announced and waited >= announce_after:
            announced = True
            if on_wait is not None:
                on_wait(lock_path, waited)
        time.sleep(min(delay, max(timeout - waited, 0.0)))
        delay = min(delay * 2, 0.25)
