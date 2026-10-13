"""Watching a directory (platform/watching.py; spec: platform; watch-event-segments design D2, D7).

Another process makes each change: watch_child.py, which prints the wall-clock time the moment its
change returned. Delays are measured from then, by the wall clock, because time.monotonic()'s
reference point is undefined across processes.
"""

import errno
import statistics
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from troupe.platform import watching
from troupe.platform.errors import WatchDirectoryMissingError, WatchUnavailableError
from troupe.platform.watching import DirectoryWatch, watch

CHILD = Path(__file__).with_name("watch_child.py")
BOUND = 0.25  # seconds: a quarter of the 1 s subscription poll this replaces


class Changer:
    """watch_child.py, changing files on command."""

    def __init__(self) -> None:
        self.process = subprocess.Popen(
            [sys.executable, str(CHILD)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
        )

    def send(self, command: str, path: Path) -> None:
        assert self.process.stdin is not None
        self.process.stdin.write(f"{command} {path}\n")
        self.process.stdin.flush()

    def done_at(self) -> float:
        assert self.process.stdout is not None
        line = self.process.stdout.readline()
        assert line.startswith("DONE "), line
        return float(line.split()[1])

    def close(self) -> None:
        assert self.process.stdin is not None
        self.process.stdin.close()
        assert self.process.wait(timeout=30) == 0


@pytest.fixture
def changer() -> Iterator[Changer]:
    child = Changer()
    yield child
    child.close()


def drain(watched: DirectoryWatch, quiet: float = 0.2) -> None:
    """Wait until ``watched`` has reported nothing for ``quiet`` seconds. One change can be
    reported as more than one wake."""
    while watched.wait(quiet):
        pass


def settled(directory: Path) -> DirectoryWatch:
    """A watch on ``directory`` with any spurious first wake used up (FSEvents gives one for a
    directory made just before it is watched)."""
    watched = watch(directory)
    drain(watched, 0.3)
    return watched


def test_another_processs_appends_each_wake_a_wait_with_a_median_delay_under_the_bound(
    tmp_path: Path, changer: Changer
) -> None:
    segment = tmp_path / "segment.jsonl"
    segment.write_bytes(b"")
    delays: list[float] = []
    with settled(tmp_path) as watched:
        for _ in range(5):
            changer.send("append", segment)
            assert watched.wait(10)
            woke = time.time()
            delays.append(woke - changer.done_at())
            drain(watched)
    assert statistics.median(delays) < BOUND, delays


def test_another_processs_new_file_wakes_a_wait(tmp_path: Path, changer: Changer) -> None:
    with settled(tmp_path) as watched:
        changer.send("create", tmp_path / "new.jsonl")
        assert watched.wait(10)
        changer.done_at()


def test_another_processs_removing_a_file_wakes_a_wait(tmp_path: Path, changer: Changer) -> None:
    doomed = tmp_path / "doomed.jsonl"
    doomed.write_bytes(b"x\n")
    with settled(tmp_path) as watched:
        changer.send("remove", doomed)
        assert watched.wait(10)
        changer.done_at()


def test_a_change_made_while_nobody_waits_is_reported_by_the_next_wait_at_once(
    tmp_path: Path, changer: Changer
) -> None:
    segment = tmp_path / "segment.jsonl"
    segment.write_bytes(b"")
    with settled(tmp_path) as watched:
        changer.send("append", segment)
        changer.done_at()
        time.sleep(0.5)  # the change is made and delivered while nobody waits
        started = time.monotonic()
        assert watched.wait(10)
        assert time.monotonic() - started < BOUND


def test_a_wait_with_nothing_changing_returns_after_its_timeout_saying_nothing_changed(
    tmp_path: Path,
) -> None:
    with settled(tmp_path) as watched:
        started = time.monotonic()
        assert not watched.wait(0.5)
        assert time.monotonic() - started >= 0.5


def test_a_directory_of_10000_files_is_watched_within_a_256_file_limit_and_wakes_on_one_growing(
    tmp_path: Path,
) -> None:
    for number in range(10_000):
        (tmp_path / f"{number:05}.jsonl").write_bytes(b"")
    watcher = subprocess.Popen(
        [sys.executable, str(CHILD), "watch", str(tmp_path), "256"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert watcher.stdout is not None
    ready = watcher.stdout.readline()
    assert ready == "READY\n", (ready, watcher.stderr.read() if watcher.stderr else "")
    with (tmp_path / "04321.jsonl").open("ab") as segment:
        segment.write(b"grown\n")
    out, err = watcher.communicate(timeout=30)
    assert out == "CHANGED\n", err


def test_closing_a_watch_wakes_a_wait_in_another_thread_at_once(tmp_path: Path) -> None:
    watched = settled(tmp_path)
    returned: list[tuple[bool, float]] = []

    def waiting() -> None:
        changed = watched.wait(None)
        returned.append((changed, time.monotonic()))

    waiter = threading.Thread(target=waiting, daemon=True)
    waiter.start()
    time.sleep(0.3)
    closed = time.monotonic()
    watched.close()
    waiter.join(timeout=5)
    assert len(returned) == 1
    changed, at = returned[0]
    assert not changed
    assert at - closed < BOUND
    assert not watched.wait(0)  # a closed watch reports nothing, and doesn't block


def test_removing_the_watched_directory_during_a_wait_wakes_it_and_the_next_wait_names_it(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "events"
    directory.mkdir()
    with settled(directory) as watched:
        threading.Timer(0.3, directory.rmdir).start()
        assert watched.wait(10)
        with pytest.raises(WatchDirectoryMissingError) as raised:
            drain(watched)
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
