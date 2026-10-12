"""Atomic file replacement (spec: platform; design D5).

Write the new bytes to a temporary file in the same directory, fsync it, give it the original's
permission bits, then rename it over the target. A reader sees the old file or the new one, never
part of either. On any failure the original is untouched and the temporary file is removed.

Platform differences, handled here so callers see one behaviour:
- POSIX: the directory is fsynced after the rename, so the rename itself is durable.
- Windows: a directory can't be fsynced (NTFS journals the rename). A target that another process
  has open can't be replaced; the replace retries with backoff, announces the wait, and gives up
  with FileInUseError. A read-only target is replaced and stays read-only, as it would on POSIX.
- Windows: while a replace completes, opening the file can briefly fail with a sharing violation.
  read_bytes retries that refusal the same bounded, announced way, so a reader still gets one
  complete version.
"""

import contextlib
import os
import stat
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

from troupe.platform.errors import FileInUseError

WaitCallback = Callable[[Path, float], None]
"""Called once when a wait has lasted ``announce_after`` seconds, with the path and time waited."""

_WINDOWS = sys.platform == "win32"


def replace_bytes(
    path: str | os.PathLike[str],
    data: bytes,
    *,
    timeout: float,
    announce_after: float,
    on_wait: WaitCallback | None = None,
) -> None:
    """Atomically replace the contents of ``path`` with ``data``, keeping its permission bits."""
    target = Path(path)
    mode = stat.S_IMODE(target.stat().st_mode) if target.exists() else None
    fd, temp_name = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.", suffix=".tmp")
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if mode is not None:
            os.chmod(temp, mode)
        _replace(
            temp, target, mode, timeout=timeout, announce_after=announce_after, on_wait=on_wait
        )
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            temp.unlink()
        raise
    _fsync_directory(target.parent)


def commit_file(
    temp: str | os.PathLike[str],
    target: str | os.PathLike[str],
    *,
    timeout: float,
    announce_after: float,
    on_wait: WaitCallback | None = None,
) -> bool:
    """Move a finished, fsynced temporary file into place, unless ``target`` already exists.

    For content-addressed files, whose name is a hash of their bytes: an existing target already
    holds the same bytes, so the temporary file is deleted and False is returned. Otherwise the
    temporary file is renamed to ``target`` (retrying, bounded and announced, while Windows refuses)
    and True is returned. The temporary file must be in the same directory tree and file system.
    """
    source = Path(temp)
    destination = Path(target)
    try:
        if destination.exists():
            source.unlink()
            return False
        _replace(
            source,
            destination,
            None,
            timeout=timeout,
            announce_after=announce_after,
            on_wait=on_wait,
        )
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            source.unlink()
        raise
    _fsync_directory(destination.parent)
    return True


def _replace(
    temp: Path,
    target: Path,
    mode: int | None,
    *,
    timeout: float,
    announce_after: float,
    on_wait: WaitCallback | None,
) -> None:
    read_only = _WINDOWS and mode is not None and not mode & stat.S_IWRITE
    started = time.monotonic()
    delay = 0.02
    announced = False
    while True:
        try:
            if read_only:
                # Windows refuses to replace a read-only file. Lift the flag for the rename only;
                # the new file already carries the read-only mode copied from the original.
                os.chmod(target, stat.S_IWRITE | stat.S_IREAD)
            os.replace(temp, target)
            return
        except PermissionError:
            if not _WINDOWS:
                raise
            if read_only:
                with contextlib.suppress(OSError):
                    os.chmod(target, stat.S_IREAD)
        # Windows: the target is open in another process (sharing violation). Wait, bounded.
        waited = time.monotonic() - started
        if waited >= timeout:
            raise FileInUseError(target, waited)
        if not announced and waited >= announce_after:
            announced = True
            if on_wait is not None:
                on_wait(target, waited)
        time.sleep(min(delay, max(timeout - waited, 0.0)))
        delay = min(delay * 2, 0.25)


def read_bytes(
    path: str | os.PathLike[str],
    *,
    timeout: float,
    announce_after: float,
    on_wait: WaitCallback | None = None,
) -> bytes:
    """Read the whole of ``path``: one complete version, even while it is being replaced."""
    target = Path(path)
    started = time.monotonic()
    delay = 0.02
    announced = False
    while True:
        try:
            return target.read_bytes()
        except PermissionError:
            if not _WINDOWS:
                raise
        # Windows: the file is mid-replace or held without read sharing. Wait, bounded.
        waited = time.monotonic() - started
        if waited >= timeout:
            raise FileInUseError(target, waited)
        if not announced and waited >= announce_after:
            announced = True
            if on_wait is not None:
                on_wait(target, waited)
        time.sleep(min(delay, max(timeout - waited, 0.0)))
        delay = min(delay * 2, 0.25)


def _fsync_directory(directory: Path) -> None:
    if _WINDOWS:
        return
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def append_bytes(path: str | os.PathLike[str], data: bytes) -> int:
    """Append ``data`` to ``path`` durably, creating the file if it is missing, and return the
    file's size before the append.

    All of ``data`` goes in through one handle opened for appending, in binary mode (on Windows a
    text-mode handle would turn line feeds into CRLF), and is fsynced before this returns. When the
    file is new, its directory is fsynced too (POSIX), so the new name survives a crash. A crash
    part-way leaves at most a prefix of ``data`` at the end of the file, never a gap or an overlap:
    readers detect that by the record framing (event-store design D4).
    """
    target = Path(path)
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_BINARY", 0)
    created = not target.exists()
    fd = os.open(target, flags, 0o644)
    try:
        before = os.fstat(fd).st_size
        view = memoryview(data)
        while view:
            written = os.write(fd, view)
            view = view[written:]
        os.fsync(fd)
    finally:
        os.close(fd)
    if created:
        _fsync_directory(target.parent)
    return before
