"""Copy-on-write file clones (spec: platform; worktree-stage design D3).

``clone_file`` makes ``dst`` a copy of ``src`` that shares its blocks where the file system can:

- macOS: ``clonefile(2)`` (APFS), with ``CLONE_NOFOLLOW``.
- Linux: the ``FICLONE`` ioctl (Btrfs, XFS and other reflink file systems), on a destination
  created exclusively.
- Windows: ``CopyFile2``, which block-clones on ReFS and Dev Drive volumes. Windows doesn't say
  whether it cloned, so the mechanism reported is ``copyfile2``, never a clone.

Where the clone isn't supported (the file system refuses it, or the two paths are on different
volumes) the file is copied instead, and the mechanism reported is ``copy``. Either way the bytes
and the permission bits are kept, a symbolic link is made again as a link without reading its
target, an existing destination is never overwritten, and a clone that fails part-way leaves no
destination behind.
"""

import contextlib
import errno
import os
import stat
import sys
from pathlib import Path
from typing import Literal

from troupe.platform.errors import CloneDestinationExistsError, CloneFailedError

CloneMechanism = Literal["clonefile", "ficlone", "copyfile2", "copy", "symlink"]
"""How a file was cloned: a copy-on-write clone (``clonefile``, ``ficlone``), Windows' CopyFile2,
which may block-clone (``copyfile2``), a plain copy (``copy``), or a link made again
(``symlink``)."""

_UNSUPPORTED = frozenset(
    code
    for code in (
        getattr(errno, "ENOTSUP", None),
        getattr(errno, "EOPNOTSUPP", None),
        errno.EXDEV,
        errno.EINVAL,
        getattr(errno, "ENOTTY", None),
        getattr(errno, "ENOSYS", None),
    )
    if code is not None
)
"""The errnos that mean "this file system can't clone this", so a plain copy is made instead."""

_FICLONE = 0x40049409
"""Linux's FICLONE ioctl request: _IOW(0x94, 9, int)."""

_CLONE_NOFOLLOW = 0x0001
"""macOS's clonefile flag that clones a symbolic link itself rather than its target."""

_COPY_FILE_FAIL_IF_EXISTS = 0x00000001
"""CopyFile2's flag that refuses an existing destination."""

_COPY_CHUNK_BYTES = 1024 * 1024

_PLATFORM = sys.platform
"""Which clone call to make; a test sets it to an unknown platform to drive the plain copy."""


def clone_file(src: str | os.PathLike[str], dst: str | os.PathLike[str]) -> CloneMechanism:
    """Clone ``src`` to ``dst``, copy-on-write where possible, and say how. ``dst`` must not exist;
    its parent directory must."""
    source, destination = Path(src), Path(dst)
    if os.path.lexists(destination):
        raise CloneDestinationExistsError(destination)
    try:
        if source.is_symlink():
            _relink(source, destination)
            return "symlink"
        if _PLATFORM == "darwin":
            return _clone_darwin(source, destination)
        if _PLATFORM == "win32":
            return _clone_windows(source, destination)
        if _PLATFORM == "linux":
            return _clone_linux(source, destination)
        return _copy_exclusive(source, destination)
    except FileExistsError as error:
        raise CloneDestinationExistsError(destination) from error
    except OSError as error:
        raise CloneFailedError(source, destination, str(error)) from error


def _relink(source: Path, destination: Path) -> None:
    target = os.readlink(source)
    os.symlink(target, destination, target_is_directory=source.is_dir())


def _copy_exclusive(source: Path, destination: Path) -> CloneMechanism:
    mode = stat.S_IMODE(source.stat().st_mode)
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0))
    try:
        _copy_into(source, fd)
    except BaseException:
        os.close(fd)
        _remove(destination)
        raise
    os.close(fd)
    _set_mode(destination, mode)
    return "copy"


def _copy_into(source: Path, fd: int) -> None:
    with source.open("rb") as reader:
        while chunk := reader.read(_COPY_CHUNK_BYTES):
            view = memoryview(chunk)
            while view:
                written = os.write(fd, view)
                view = view[written:]


def _set_mode(destination: Path, mode: int) -> None:
    os.chmod(destination, mode)


def _remove(destination: Path) -> None:
    with contextlib.suppress(FileNotFoundError):
        destination.unlink()


if sys.platform == "darwin":
    import ctypes

    _libc = ctypes.CDLL(None, use_errno=True)
    _clonefile = _libc.clonefile
    _clonefile.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint32]
    _clonefile.restype = ctypes.c_int

    def _call_clonefile(source: Path, destination: Path) -> int:
        """clonefile(2): 0 on success, otherwise the errno it set."""
        if _clonefile(os.fsencode(source), os.fsencode(destination), _CLONE_NOFOLLOW) == 0:
            return 0
        return ctypes.get_errno()

    def _clone_darwin(source: Path, destination: Path) -> CloneMechanism:
        code = _call_clonefile(source, destination)
        if code == 0:
            return "clonefile"
        if code in _UNSUPPORTED:
            _remove(destination)
            return _copy_exclusive(source, destination)
        raise OSError(code, os.strerror(code), str(destination))

else:

    def _clone_darwin(source: Path, destination: Path) -> CloneMechanism:
        raise NotImplementedError("clonefile exists only on macOS")


if sys.platform == "linux":
    import fcntl

    def _ficlone(fd: int, source_fd: int) -> None:
        """The FICLONE ioctl: ``fd`` shares ``source_fd``'s blocks, or OSError."""
        fcntl.ioctl(fd, _FICLONE, source_fd)

    def _clone_linux(source: Path, destination: Path) -> CloneMechanism:
        mode = stat.S_IMODE(source.stat().st_mode)
        with source.open("rb") as reader:
            fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
            try:
                try:
                    _ficlone(fd, reader.fileno())
                    mechanism: CloneMechanism = "ficlone"
                except OSError as error:
                    if error.errno not in _UNSUPPORTED:
                        raise
                    os.ftruncate(fd, 0)
                    _copy_into(source, fd)
                    mechanism = "copy"
            except BaseException:
                os.close(fd)
                _remove(destination)
                raise
            os.close(fd)
        _set_mode(destination, mode)
        return mechanism

else:

    def _clone_linux(source: Path, destination: Path) -> CloneMechanism:
        raise NotImplementedError("FICLONE exists only on Linux")


if sys.platform == "win32":
    import _winapi

    def _clone_windows(source: Path, destination: Path) -> CloneMechanism:
        try:
            _winapi.CopyFile2(str(source), str(destination), _COPY_FILE_FAIL_IF_EXISTS)
        except OSError as error:
            if error.winerror in (80, 183):  # ERROR_FILE_EXISTS, ERROR_ALREADY_EXISTS
                raise FileExistsError(
                    errno.EEXIST, "the destination exists", str(destination)
                ) from error
            _remove(destination)
            raise
        return "copyfile2"

else:

    def _clone_windows(source: Path, destination: Path) -> CloneMechanism:
        raise NotImplementedError("CopyFile2 exists only on Windows")
