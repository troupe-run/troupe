"""Watching a directory, with every change made in this process (platform/watching.py; spec:
platform; watch-event-segments design D2, D7). A wait with nothing changing returns after its
timeout, even when the platform gives up early, closing a watch wakes a wait in another thread at
once, and removing the watched directory wakes a wait and the next one names it missing. Watching
a missing directory, a file, or a directory the OS call refuses fails naming the directory and
the reason.

Its tests that start a process, open a socket or use a git theatre are in
integration/test_platform_watching_integration.py."""

import errno
import sys
import threading
import time
from pathlib import Path

import pytest

from platform_watching_shared import drain, settled
from storetesting import BOUND, SLOW_STRETCH_SECONDS, WITHIN
from troupe.platform import watching
from troupe.platform.errors import WatchDirectoryMissingError, WatchUnavailableError
from troupe.platform.watching import DirectoryWatch, watch


def test_a_wait_with_nothing_changing_returns_after_its_timeout_saying_nothing_changed(
    tmp_path: Path,
) -> None:
    # A watch may report a change that wasn't one, and FSEvents can report a fresh directory's
    # creation more than SETTLE late under load (#446's family, load-flakes design D7). So a
    # reported change is tried again, within the slow stretch's budget; the first wait that reports
    # nothing must have lasted its timeout. A watch that never goes quiet fails once it's spent.
    with settled(tmp_path) as watched:
        budget = time.monotonic() + SLOW_STRETCH_SECONDS
        while True:
            started = time.monotonic()
            if not watched.wait(0.5):
                break
            assert time.monotonic() < budget, "the watch never went quiet"
        assert time.monotonic() - started >= 0.5


def test_closing_a_watch_wakes_a_wait_in_another_thread_at_once(tmp_path: Path) -> None:
    watched = settled(tmp_path)
    closed_wait_returned: list[float] = []

    def waiting() -> None:
        while watched.wait(None):
            pass  # a spurious change (allowed) isn't the close; wait again
        closed_wait_returned.append(time.monotonic())

    waiter = threading.Thread(target=waiting, daemon=True)
    waiter.start()
    time.sleep(0.3)
    closed = time.monotonic()
    watched.close()
    waiter.join(timeout=5)
    assert len(closed_wait_returned) == 1, "the waiting thread never returned"
    assert closed <= closed_wait_returned[0] < closed + BOUND
    assert not watched.wait(0)  # a closed watch reports nothing, and doesn't block


def test_removing_the_watched_directory_during_a_wait_wakes_it_and_the_next_wait_names_it(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "events"
    directory.mkdir()
    with settled(directory) as watched:
        threading.Timer(0.3, directory.rmdir).start()
        assert watched.wait(WITHIN)
        with pytest.raises(WatchDirectoryMissingError) as raised:
            drain(watched)
    assert raised.value.directory == directory


@pytest.mark.skipif(sys.platform != "win32", reason="a deleted directory held open is Windows' own")
def test_on_windows_a_watched_directory_pending_deletion_is_named_missing_not_unwatchable(
    tmp_path: Path,
) -> None:
    # The watch's own handle keeps the removed directory, pending deletion, until it closes, so
    # its path can still look like a directory, and re-issuing the watch is refused
    # (ERROR_ACCESS_DENIED). The backend is asked directly, past DirectoryWatch's own is_dir()
    # check, which is what let this pass only some of the time (#100: 11 of 65 Windows rounds).
    directory = tmp_path / "events"
    directory.mkdir()
    with settled(directory) as watched:
        directory.rmdir()
        backend = watched._backend

        def wait_past_the_removal() -> None:
            for _ in range(3):  # the removal's own change, then the refused re-issue
                backend.wait(2.0)

        with pytest.raises(WatchDirectoryMissingError) as raised:
            wait_past_the_removal()
    assert raised.value.directory == directory


def test_watching_a_directory_that_doesnt_exist_fails_naming_it(tmp_path: Path) -> None:
    missing = tmp_path / "events"
    with pytest.raises(WatchDirectoryMissingError) as raised:
        watch(missing)
    assert raised.value.directory == missing
    assert str(missing) in str(raised.value)


def test_watching_a_file_fails_saying_it_isnt_a_directory(tmp_path: Path) -> None:
    file = tmp_path / "segment.jsonl"
    file.write_bytes(b"")
    with pytest.raises(WatchUnavailableError) as raised:
        watch(file)
    assert raised.value.directory == file
    assert raised.value.reason == "it isn't a directory"


@pytest.fixture
def refused(monkeypatch: pytest.MonkeyPatch) -> str:
    """Make this platform's OS call refuse the watch, and return what the reason must mention."""
    if sys.platform == "linux":

        def no_watches_left(fd: int, directory: Path) -> None:
            raise OSError(errno.ENOSPC, "inotify_add_watch: No space left on device")

        monkeypatch.setattr(watching, "_add_watch", no_watches_left)
        return "fs.inotify.max_user_watches"
    if sys.platform == "darwin":
        monkeypatch.setattr(watching, "_start", lambda stream: False)
        return "FSEventStreamStart failed"
    if sys.platform == "win32":

        def incorrect_function(handle: int, buffer: object, overlapped: object) -> None:
            raise OSError(errno.EINVAL, "Incorrect function", None, 1)  # ERROR_INVALID_FUNCTION

        monkeypatch.setattr(watching, "_read_directory_changes", incorrect_function)
        return "Incorrect function"
    raise AssertionError(f"no watching on {sys.platform}")


def test_a_refused_watch_simulated_at_the_os_call_fails_naming_the_directory_and_the_reason(
    tmp_path: Path, refused: str
) -> None:
    with pytest.raises(WatchUnavailableError) as raised:
        watch(tmp_path)
    assert raised.value.directory == tmp_path
    assert refused in raised.value.reason
    assert str(tmp_path) in str(raised.value)


class _EarlyBackend(watching._Backend):
    """A backend whose wait gives up early twice, as Windows' timer and Linux's empty poll can."""

    def __init__(self) -> None:
        self.asked: list[float | None] = []

    def wait(self, timeout: float | None) -> bool:
        self.asked.append(timeout)
        if len(self.asked) <= 2:
            return False  # "timed out", well before the timeout it was given
        if timeout is not None:
            time.sleep(timeout)
        return False

    def interrupt(self) -> None:
        pass

    def release(self) -> None:
        pass


def test_a_wait_returns_after_its_timeout_even_when_the_platform_gives_up_early(
    tmp_path: Path,
) -> None:
    # Windows' WaitForMultipleObjects can time out a little before time.monotonic says the timeout
    # has passed (#100, CI run 38568514789), and Linux's poll can report ready with nothing to
    # read. "Returns after its timeout" is DirectoryWatch's promise, kept on every platform.
    backend = _EarlyBackend()
    watched = DirectoryWatch(tmp_path, backend)
    started = time.monotonic()
    assert not watched.wait(0.3)
    assert time.monotonic() - started >= 0.3
    # Asked again for what was left: at least past the two early returns, and more if the fake's
    # own sleep for the remainder ends early too, as Windows' timer can (CI run 38734673892).
    assert len(backend.asked) >= 3
    # Never more than the timeout, give or take float rounding: (t + 0.3) - t can come out as
    # 0.30000000000000004 when time.monotonic hasn't ticked, as on Windows Python 3.12 (15.6 ms).
    assert all(each is not None and 0 <= each <= 0.3 + 1e-9 for each in backend.asked)
