"""Watching a directory for changes (spec: platform; watch-event-segments design D1, D2).

``watch(directory)`` returns a DirectoryWatch whose ``wait(timeout)`` returns True once something
in the directory has changed since the last wait returned: a file created, written, renamed in or
out, replaced or removed, or the directory itself removed. It reports only that something changed,
never what, because callers rescan anyway. A spurious True is allowed; a missed change isn't. The
OS buffers changes between waits, so a change made while nobody waits is reported by the next one.

Each platform's own notification is reached through ctypes, with one fixed set of handles per
watch, however many files the directory holds:
- Linux: inotify, one watch on the directory, waited on with poll() beside a self-pipe.
- macOS: an FSEvents stream on the directory (file events, no defer, latency 0), delivered on a
  private serial dispatch queue. FSEvents watches subdirectories too: a superset, and harmless.
- Windows: ReadDirectoryChangesW on the directory, kept outstanding with overlapped I/O, waited on
  with WaitForMultipleObjects beside a close event. A buffer overflow counts as a change.

A directory that doesn't exist raises WatchDirectoryMissingError, and one the OS won't watch raises
WatchUnavailableError with the OS's reason. Neither ever returns a watch that doesn't wake. If the
watched directory is removed later, the next wait raises WatchDirectoryMissingError.

One thread waits at a time. ``close`` may be called from any thread; it wakes a waiting thread,
then releases the handles once that wait has returned.
"""

import contextlib
import errno
import os
import sys
import threading
import time
from pathlib import Path
from types import TracebackType
from typing import Self

from troupe.platform.errors import WatchDirectoryMissingError, WatchUnavailableError


class _Backend:
    """One platform's notification for one directory. Only DirectoryWatch calls it."""

    def wait(self, timeout: float | None) -> bool:
        """Block until a change (True), the timeout (False) or ``interrupt`` (False)."""
        raise NotImplementedError

    def interrupt(self) -> None:
        """Wake a thread blocked in ``wait``. Called from any thread, at most once."""
        raise NotImplementedError

    def release(self) -> None:
        """Free the handles. Called once, after no thread is in ``wait``."""
        raise NotImplementedError


class DirectoryWatch:
    """A watch on one directory. Use it as a context manager, or call ``close``."""

    def __init__(self, directory: Path, backend: _Backend) -> None:
        self.directory = directory
        self._backend = backend
        self._waiting = threading.Lock()
        self._closing = threading.Lock()
        self._closed = False

    def wait(self, timeout: float | None) -> bool:
        """Whether anything in the directory changed since the last wait returned, waiting up to
        ``timeout`` seconds (None: until a change or ``close``) for something to."""
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._waiting:
            while True:
                if self._closed:
                    return False
                if not self.directory.is_dir():
                    raise WatchDirectoryMissingError(self.directory)
                remaining = None if deadline is None else max(0.0, deadline - time.monotonic())
                if self._backend.wait(remaining):
                    return True
                if deadline is not None and time.monotonic() >= deadline:
                    return False
                # The platform gave up early: Windows' wait runs on its own timer, which can end
                # before time.monotonic's, and Linux's poll can say ready with nothing to read.
                # Wait again for what's left, so returning after the timeout holds everywhere.

    def close(self) -> None:
        """Release the watch's handles, waking a wait in another thread first."""
        with self._closing:
            if self._closed:
                return
            self._closed = True
            self._backend.interrupt()
            with self._waiting:  # the woken wait returns, then nothing else can start one
                self._backend.release()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()


def watch(directory: Path) -> DirectoryWatch:
    """Start watching ``directory``. Raises WatchDirectoryMissingError if it doesn't exist, and
    WatchUnavailableError if it isn't a directory or the OS refuses to watch it."""
    if not directory.exists():
        raise WatchDirectoryMissingError(directory)
    if not directory.is_dir():
        raise WatchUnavailableError(directory, "it isn't a directory")
    return DirectoryWatch(directory, _open(directory))


def _milliseconds(timeout: float | None) -> int:
    """A timeout for a call that takes whole milliseconds, never rounding a short one to 0."""
    if timeout is None:
        return -1
    return max(0, int(timeout * 1000 + 0.999))


if sys.platform == "linux":
    import ctypes
    import select

    _libc = ctypes.CDLL(None, use_errno=True)
    _libc.inotify_init1.restype = ctypes.c_int
    _libc.inotify_init1.argtypes = [ctypes.c_int]
    _libc.inotify_add_watch.restype = ctypes.c_int
    _libc.inotify_add_watch.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_uint32]

    _IN_MODIFY = 0x00000002
    _IN_ATTRIB = 0x00000004
    _IN_CLOSE_WRITE = 0x00000008
    _IN_MOVED_FROM = 0x00000040
    _IN_MOVED_TO = 0x00000080
    _IN_CREATE = 0x00000100
    _IN_DELETE = 0x00000200
    _IN_DELETE_SELF = 0x00000400
    _IN_MOVE_SELF = 0x00000800
    _IN_ONLYDIR = 0x01000000
    _MASK = (
        _IN_MODIFY
        | _IN_ATTRIB
        | _IN_CLOSE_WRITE
        | _IN_MOVED_FROM
        | _IN_MOVED_TO
        | _IN_CREATE
        | _IN_DELETE
        | _IN_DELETE_SELF
        | _IN_MOVE_SELF
        | _IN_ONLYDIR
    )

    _REASONS = {
        errno.ENOSPC: "the user's limit on inotify watches is reached "
        "(raise fs.inotify.max_user_watches)",
        errno.EMFILE: "the user's limit on inotify instances is reached "
        "(raise fs.inotify.max_user_instances)",
        errno.ENOTDIR: "it isn't a directory",
    }

    def _inotify_init() -> int:
        fd: int = _libc.inotify_init1(os.O_NONBLOCK | os.O_CLOEXEC)
        if fd < 0:
            number = ctypes.get_errno()
            raise OSError(number, f"inotify_init1: {os.strerror(number)}")
        return fd

    def _add_watch(fd: int, directory: Path) -> None:
        if _libc.inotify_add_watch(fd, os.fsencode(directory), _MASK) < 0:
            number = ctypes.get_errno()
            raise OSError(number, f"inotify_add_watch: {os.strerror(number)}")

    class _Inotify(_Backend):
        def __init__(self, directory: Path) -> None:
            self._fd = _inotify_init()
            try:
                _add_watch(self._fd, directory)
                self._wake_read, self._wake_write = os.pipe()
            except BaseException:
                os.close(self._fd)
                raise
            self._poll = select.poll()
            self._poll.register(self._fd, select.POLLIN)
            self._poll.register(self._wake_read, select.POLLIN)

        def wait(self, timeout: float | None) -> bool:
            ready = {fd for fd, _ in self._poll.poll(_milliseconds(timeout))}
            if self._wake_read in ready:
                return False
            if self._fd not in ready:
                return False
            changed = False
            while True:  # drain every queued event: one wait reports them all
                try:
                    if not os.read(self._fd, 65536):
                        break
                except BlockingIOError:
                    break
                changed = True
            return changed

        def interrupt(self) -> None:
            os.write(self._wake_write, b"x")

        def release(self) -> None:
            for fd in (self._fd, self._wake_read, self._wake_write):
                os.close(fd)

    def _open(directory: Path) -> _Backend:
        try:
            return _Inotify(directory)
        except OSError as error:
            if error.errno == errno.ENOENT:
                raise WatchDirectoryMissingError(directory) from error
            reason = _REASONS.get(error.errno or 0, str(error))
            raise WatchUnavailableError(directory, f"{error.strerror}: {reason}") from error

elif sys.platform == "darwin":
    import ctypes

    _cf = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
    _cs = ctypes.CDLL("/System/Library/Frameworks/CoreServices.framework/CoreServices")
    _dispatch = ctypes.CDLL("/usr/lib/system/libdispatch.dylib")

    _CF_STRING_ENCODING_UTF8 = 0x08000100  # kCFStringEncodingUTF8
    _EVENT_ID_SINCE_NOW = 0xFFFFFFFFFFFFFFFF  # kFSEventStreamEventIdSinceNow
    _FLAG_NO_DEFER = 0x00000002  # kFSEventStreamCreateFlagNoDefer
    _FLAG_WATCH_ROOT = 0x00000004  # kFSEventStreamCreateFlagWatchRoot
    _FLAG_FILE_EVENTS = 0x00000010  # kFSEventStreamCreateFlagFileEvents

    _Callback = ctypes.CFUNCTYPE(  # FSEventStreamCallback
        None,
        ctypes.c_void_p,  # ConstFSEventStreamRef streamRef
        ctypes.c_void_p,  # void *clientCallBackInfo
        ctypes.c_size_t,  # size_t numEvents
        ctypes.c_void_p,  # void *eventPaths
        ctypes.POINTER(ctypes.c_uint32),  # const FSEventStreamEventFlags eventFlags[]
        ctypes.POINTER(ctypes.c_uint64),  # const FSEventStreamEventId eventIds[]
    )
    _Function = ctypes.CFUNCTYPE(None, ctypes.c_void_p)  # dispatch_function_t

    _cf.CFStringCreateWithCString.restype = ctypes.c_void_p
    _cf.CFStringCreateWithCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32]
    _cf.CFArrayCreate.restype = ctypes.c_void_p
    _cf.CFArrayCreate.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.c_long,
        ctypes.c_void_p,
    ]
    _cf.CFRelease.restype = None
    _cf.CFRelease.argtypes = [ctypes.c_void_p]

    _cs.FSEventStreamCreate.restype = ctypes.c_void_p
    _cs.FSEventStreamCreate.argtypes = [
        ctypes.c_void_p,  # CFAllocatorRef allocator
        _Callback,  # FSEventStreamCallback callback
        ctypes.c_void_p,  # FSEventStreamContext *context
        ctypes.c_void_p,  # CFArrayRef pathsToWatch
        ctypes.c_uint64,  # FSEventStreamEventId sinceWhen
        ctypes.c_double,  # CFTimeInterval latency
        ctypes.c_uint32,  # FSEventStreamCreateFlags flags
    ]
    _cs.FSEventStreamSetDispatchQueue.restype = None
    _cs.FSEventStreamSetDispatchQueue.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    _cs.FSEventStreamStart.restype = ctypes.c_ubyte  # Boolean
    _cs.FSEventStreamStart.argtypes = [ctypes.c_void_p]
    for _name in ("FSEventStreamStop", "FSEventStreamInvalidate", "FSEventStreamRelease"):
        getattr(_cs, _name).restype = None
        getattr(_cs, _name).argtypes = [ctypes.c_void_p]

    _dispatch.dispatch_queue_create.restype = ctypes.c_void_p
    _dispatch.dispatch_queue_create.argtypes = [ctypes.c_char_p, ctypes.c_void_p]
    _dispatch.dispatch_sync_f.restype = None
    _dispatch.dispatch_sync_f.argtypes = [ctypes.c_void_p, ctypes.c_void_p, _Function]
    _dispatch.dispatch_release.restype = None
    _dispatch.dispatch_release.argtypes = [ctypes.c_void_p]

    def _do_nothing(context: int | None) -> None:
        """Run on a queue with dispatch_sync_f, so every callback queued before it has run."""

    _nothing = _Function(_do_nothing)

    def _start(stream: int) -> bool:
        return bool(_cs.FSEventStreamStart(stream))

    class _FSEvents(_Backend):
        def __init__(self, directory: Path) -> None:
            self._condition = threading.Condition()
            self._changed = False
            self._interrupted = False
            # Kept referenced for as long as the stream lives: FSEvents calls it from its queue.
            self._callback = _Callback(self._on_events)
            path = _cf.CFStringCreateWithCString(
                None, os.fsencode(directory.resolve()), _CF_STRING_ENCODING_UTF8
            )
            if not path:
                raise WatchUnavailableError(directory, "its path couldn't be passed to FSEvents")
            values = (ctypes.c_void_p * 1)(path)
            paths = _cf.CFArrayCreate(None, values, 1, None)
            try:
                self._stream = _cs.FSEventStreamCreate(
                    None,
                    self._callback,
                    None,
                    paths,
                    _EVENT_ID_SINCE_NOW,
                    0.0,
                    _FLAG_FILE_EVENTS | _FLAG_NO_DEFER | _FLAG_WATCH_ROOT,
                )
            finally:
                if paths:
                    _cf.CFRelease(paths)
                _cf.CFRelease(path)
            if not self._stream:
                raise WatchUnavailableError(directory, "FSEventStreamCreate failed")
            self._queue = _dispatch.dispatch_queue_create(b"run.troupe.watching", None)
            _cs.FSEventStreamSetDispatchQueue(self._stream, self._queue)
            if not _start(self._stream):
                self._discard(started=False)
                raise WatchUnavailableError(
                    directory, "FSEventStreamStart failed: the FSEvents service won't watch it"
                )

        def _on_events(
            self,
            stream: int | None,
            info: int | None,
            count: int,
            paths: int | None,
            flags: object,
            ids: object,
        ) -> None:
            with self._condition:
                self._changed = True
                self._condition.notify_all()

        def wait(self, timeout: float | None) -> bool:
            deadline = None if timeout is None else time.monotonic() + timeout
            with self._condition:
                while not (self._changed or self._interrupted):
                    remaining = None if deadline is None else deadline - time.monotonic()
                    if remaining is not None and remaining <= 0:
                        return False
                    self._condition.wait(remaining)
                changed, self._changed = self._changed, False
                return changed and not self._interrupted

        def interrupt(self) -> None:
            with self._condition:
                self._interrupted = True
                self._condition.notify_all()

        def release(self) -> None:
            self._discard(started=True)

        def _discard(self, *, started: bool) -> None:
            if started:
                _cs.FSEventStreamStop(self._stream)
            _cs.FSEventStreamInvalidate(self._stream)
            # Let any callback already queued finish before the stream and callback go away.
            _dispatch.dispatch_sync_f(self._queue, None, _nothing)
            _cs.FSEventStreamRelease(self._stream)
            _dispatch.dispatch_release(self._queue)

    def _open(directory: Path) -> _Backend:
        return _FSEvents(directory)

elif sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    _FILE_LIST_DIRECTORY = 0x0001
    _FILE_READ_ATTRIBUTES = 0x0080
    _FILE_SHARE_ALL = 0x00000001 | 0x00000002 | 0x00000004  # read, write, delete
    _OPEN_EXISTING = 3
    _FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
    _FILE_FLAG_OVERLAPPED = 0x40000000
    _INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value
    _FILE_NOTIFY_CHANGE_FILE_NAME = 0x00000001
    _FILE_NOTIFY_CHANGE_DIR_NAME = 0x00000002
    _FILE_NOTIFY_CHANGE_SIZE = 0x00000008
    _FILE_NOTIFY_CHANGE_LAST_WRITE = 0x00000010
    _FILTER = (
        _FILE_NOTIFY_CHANGE_FILE_NAME
        | _FILE_NOTIFY_CHANGE_DIR_NAME
        | _FILE_NOTIFY_CHANGE_SIZE
        | _FILE_NOTIFY_CHANGE_LAST_WRITE
    )
    _WAIT_OBJECT_0 = 0x00000000
    _WAIT_TIMEOUT = 0x00000102
    _INFINITE = 0xFFFFFFFF
    _ERROR_FILE_NOT_FOUND = 2
    _ERROR_PATH_NOT_FOUND = 3
    _BUFFER_BYTES = 65536  # the most a network share accepts; a fuller burst is an overflow
    _FILE_STANDARD_INFO_CLASS = 1  # FileStandardInfo

    class _StandardInfo(ctypes.Structure):
        _fields_ = [  # the layout of FILE_STANDARD_INFO
            ("AllocationSize", ctypes.c_int64),
            ("EndOfFile", ctypes.c_int64),
            ("NumberOfLinks", wintypes.DWORD),
            ("DeletePending", wintypes.BOOLEAN),
            ("Directory", wintypes.BOOLEAN),
        ]

    class _Overlapped(ctypes.Structure):
        _fields_ = [  # the layout of OVERLAPPED, with its offset union as two DWORDs
            ("Internal", ctypes.c_size_t),
            ("InternalHigh", ctypes.c_size_t),
            ("Offset", wintypes.DWORD),
            ("OffsetHigh", wintypes.DWORD),
            ("hEvent", wintypes.HANDLE),
        ]

    _kernel32.CreateFileW.restype = wintypes.HANDLE
    _kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    _kernel32.CreateEventW.restype = wintypes.HANDLE
    _kernel32.CreateEventW.argtypes = [
        ctypes.c_void_p,
        wintypes.BOOL,
        wintypes.BOOL,
        ctypes.c_void_p,
    ]
    _kernel32.ReadDirectoryChangesW.restype = wintypes.BOOL
    _kernel32.ReadDirectoryChangesW.argtypes = [
        wintypes.HANDLE,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.BOOL,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.POINTER(_Overlapped),
        ctypes.c_void_p,
    ]
    _kernel32.GetOverlappedResult.restype = wintypes.BOOL
    _kernel32.GetOverlappedResult.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(_Overlapped),
        ctypes.POINTER(wintypes.DWORD),
        wintypes.BOOL,
    ]
    _kernel32.WaitForMultipleObjects.restype = wintypes.DWORD
    _kernel32.WaitForMultipleObjects.argtypes = [
        wintypes.DWORD,
        ctypes.POINTER(wintypes.HANDLE),
        wintypes.BOOL,
        wintypes.DWORD,
    ]
    _kernel32.GetFileInformationByHandleEx.restype = wintypes.BOOL
    _kernel32.GetFileInformationByHandleEx.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    _kernel32.CancelIoEx.restype = wintypes.BOOL
    _kernel32.CancelIoEx.argtypes = [wintypes.HANDLE, ctypes.POINTER(_Overlapped)]
    for _name in ("ResetEvent", "SetEvent", "CloseHandle"):
        getattr(_kernel32, _name).restype = wintypes.BOOL
        getattr(_kernel32, _name).argtypes = [wintypes.HANDLE]

    def _read_directory_changes(
        handle: int, buffer: ctypes.Array[ctypes.c_char], overlapped: _Overlapped
    ) -> None:
        if not _kernel32.ReadDirectoryChangesW(
            handle, buffer, len(buffer), False, _FILTER, None, ctypes.byref(overlapped), None
        ):
            raise ctypes.WinError(ctypes.get_last_error())

    class _ReadDirectoryChanges(_Backend):
        def __init__(self, directory: Path) -> None:
            self._directory = directory
            self._handle = _kernel32.CreateFileW(
                str(directory),
                _FILE_LIST_DIRECTORY | _FILE_READ_ATTRIBUTES,
                _FILE_SHARE_ALL,
                None,
                _OPEN_EXISTING,
                _FILE_FLAG_BACKUP_SEMANTICS | _FILE_FLAG_OVERLAPPED,
                None,
            )
            if self._handle in (None, _INVALID_HANDLE_VALUE):
                raise ctypes.WinError(ctypes.get_last_error())
            self._changed_event = _kernel32.CreateEventW(None, True, False, None)
            self._close_event = _kernel32.CreateEventW(None, True, False, None)
            self._buffer = ctypes.create_string_buffer(_BUFFER_BYTES)
            self._overlapped = _Overlapped(hEvent=self._changed_event)
            self._outstanding = False
            try:
                self._issue()
            except BaseException:
                self._close_handles()
                raise

        def _issue(self) -> None:
            _kernel32.ResetEvent(self._changed_event)
            _read_directory_changes(self._handle, self._buffer, self._overlapped)
            self._outstanding = True

        def _delete_pending(self) -> bool:
            """Whether the watched directory was deleted while this watch holds it open. Windows
            keeps it, pending deletion, until the last handle closes, and refuses to watch it
            (ERROR_ACCESS_DENIED), so the refusal alone can't tell missing from unwatchable."""
            info = _StandardInfo()
            if not _kernel32.GetFileInformationByHandleEx(
                self._handle, _FILE_STANDARD_INFO_CLASS, ctypes.byref(info), ctypes.sizeof(info)
            ):
                return False  # can't tell: the refusal stands as unwatchable, never a guess
            return bool(info.DeletePending)

        def wait(self, timeout: float | None) -> bool:
            if not self._outstanding:  # re-issuing failed after the last change: try once more
                try:
                    self._issue()
                except OSError as error:
                    if self._delete_pending():
                        raise WatchDirectoryMissingError(self._directory) from error
                    raise WatchUnavailableError(self._directory, str(error)) from error
            handles = (wintypes.HANDLE * 2)(self._changed_event, self._close_event)
            milliseconds = _milliseconds(timeout)
            result = _kernel32.WaitForMultipleObjects(
                2, handles, False, _INFINITE if milliseconds < 0 else milliseconds
            )
            if result != _WAIT_OBJECT_0:
                return False  # the timeout, or the close event
            transferred = wintypes.DWORD()
            _kernel32.GetOverlappedResult(
                self._handle, ctypes.byref(self._overlapped), ctypes.byref(transferred), False
            )
            # Whatever completed the read (changes, an overflow with no bytes, or an error such as
            # the directory going away) means something changed. Re-issue for the next wait.
            self._outstanding = False
            with contextlib.suppress(OSError):  # reported by the next wait, which tries again
                self._issue()
            return True

        def interrupt(self) -> None:
            _kernel32.SetEvent(self._close_event)

        def release(self) -> None:
            if self._outstanding:
                _kernel32.CancelIoEx(self._handle, ctypes.byref(self._overlapped))
                transferred = wintypes.DWORD()
                # Wait for the cancellation, so the OS no longer writes into the buffer.
                _kernel32.GetOverlappedResult(
                    self._handle, ctypes.byref(self._overlapped), ctypes.byref(transferred), True
                )
            self._close_handles()

        def _close_handles(self) -> None:
            for handle in (self._handle, self._changed_event, self._close_event):
                _kernel32.CloseHandle(handle)

    def _open(directory: Path) -> _Backend:
        try:
            return _ReadDirectoryChanges(directory)
        except OSError as error:
            if getattr(error, "winerror", None) in (_ERROR_FILE_NOT_FOUND, _ERROR_PATH_NOT_FOUND):
                raise WatchDirectoryMissingError(directory) from error
            raise WatchUnavailableError(directory, str(error)) from error

else:

    def _open(directory: Path) -> _Backend:
        raise WatchUnavailableError(directory, f"troupe can't watch directories on {sys.platform}")
