"""The store across processes (spec: event-store, "Versions are unique within a stream" and
"Writers wait for each other, bounded and announced"; design D10)."""

import statistics
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from eventsourcing.persistence import Notification

from gitrepo import make_repo
from protocol_schemas import check_notice
from storetesting import event
from troupe.core.files import directory_lock
from troupe.core.vcs import load_vcs
from troupe.platform import watching
from troupe.platform.errors import WatchUnavailableError
from troupe.platform.watching import DirectoryWatch
from troupe_store_text import TextApplicationRecorder, open_store
from troupe_store_text import store as store_module
from troupe_store_text.store import TextStore, shared_store
from troupe_vcs_git import GitAdapter

CHILD = """
import sys, time
from pathlib import Path
from uuid import UUID
sys.path.insert(0, {tests!r})
from eventsourcing.persistence import IntegrityError
from storetesting import event
from troupe.core.errors import TroupeError
from troupe.core.vcs import load_vcs
from troupe_store_text.store import TextStore

theatre = Path({theatre!r})
go = Path({go!r})
while not go.exists():
    time.sleep(0.005)
store = TextStore(
    theatre,
    load_vcs("files", theatre),
    lock_timeout={timeout},
    lock_announce_after=0.1,
    on_wait=lambda path, waited: print("waiting", path, flush=True),
)
try:
    store.insert([event(UUID({stream!r}), {version}, by={who!r})])
except IntegrityError:
    print("integrity-error", flush=True)
except TroupeError as error:
    print(error.code, flush=True)
else:
    print("recorded", flush=True)
"""

TESTS = str(Path(__file__).resolve().parents[2] / "troupe" / "tests")


def child(
    theatre: Path,
    go: Path,
    stream: str,
    *,
    version: int = 1,
    timeout: float = 30.0,
    who: str = "child",
) -> subprocess.Popen[str]:
    code = CHILD.format(
        tests=TESTS,
        theatre=str(theatre),
        go=str(go),
        stream=stream,
        version=version,
        timeout=timeout,
        who=who,
    )
    return subprocess.Popen(
        [sys.executable, "-c", code], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )


def outcome(stdout: str) -> str:
    """A child's outcome: its last line. Every earlier line must be a lock-wait announcement,
    which the spec requires of a writer that waits ("Writers wait for each other, bounded and
    announced")."""
    *announcements, last = stdout.strip().splitlines()
    for line in announcements:
        assert line.startswith("waiting "), f"unexpected output before the outcome: {line!r}"
    return last


WINDOWS_LOSER = (
    "waiting C:\\Users\\runneradmin\\AppData\\Local\\Temp\\pytest-of-runneradmin\\pytest-0\\"
    "test_two_processes_racing_for_0\\.troupe\\local\\.lock\r\nintegrity-error\r\n"
)
"""A losing racer's real stdout from Windows CI (#43): it announced its wait, then its outcome."""


def test_a_child_s_outcome_is_its_last_line_after_its_announcements() -> None:
    assert outcome(WINDOWS_LOSER) == "integrity-error"
    assert outcome("waiting a\nwaiting b\nrecorded\n") == "recorded"


def test_a_child_s_outcome_without_announcements_is_its_only_line() -> None:
    assert outcome("recorded\r\n") == "recorded"


def test_an_unexpected_line_before_a_child_s_outcome_fails_naming_it() -> None:
    with pytest.raises(AssertionError, match="Traceback"):
        outcome("Traceback (most recent call last):\nrecorded\n")


def test_two_processes_racing_for_one_version_give_exactly_one_integrity_error(
    tmp_path: Path,
) -> None:
    stream = str(uuid4())
    go = tmp_path / "go"
    racers = [child(tmp_path, go, stream, who=f"racer-{i}") for i in range(2)]
    time.sleep(0.5)
    go.touch()
    outcomes = sorted(outcome(racer.communicate(timeout=60)[0]) for racer in racers)
    assert outcomes == ["integrity-error", "recorded"]
    store = open_store(tmp_path, load_vcs("files", tmp_path))
    assert len(store.history(UUID(stream))) == 1


def test_a_writer_waiting_for_another_process_announces_it_and_times_out(
    tmp_path: Path,
) -> None:
    local = tmp_path / ".troupe" / "local"
    local.mkdir(parents=True)
    go = tmp_path / "go"
    go.touch()
    with directory_lock(local):
        waiting = child(tmp_path, go, str(uuid4()), timeout=1.0)
        out, err = waiting.communicate(timeout=60)
    assert "waiting" in out, err
    assert out.strip().endswith("lock.timeout"), err


def test_another_processs_write_wakes_this_processs_subscription(tmp_path: Path) -> None:
    # The poll and the check are far longer than the test, so only a notification can wake it.
    store = shared_store(
        tmp_path, lambda: load_vcs("files", tmp_path), poll_seconds=60, check_seconds=60
    )
    recorder = TextApplicationRecorder(store)
    received: list[Notification] = []
    with recorder.subscribe(gt=0) as subscription:

        def first() -> None:
            received.append(next(subscription))

        reader = threading.Thread(target=first, daemon=True)
        reader.start()
        go = tmp_path / "go"
        go.touch()
        writer = child(tmp_path, go, str(uuid4()))
        assert outcome(writer.communicate(timeout=60)[0]) == "recorded"
        reader.join(timeout=10)
        subscription.stop()
    assert [n.id for n in received] == [1]


def test_recording_in_a_git_theatre_leaves_no_lock_or_local_file_for_git_to_see(
    tmp_path: Path,
) -> None:
    repo = make_repo(tmp_path)
    store = open_store(repo.path, GitAdapter(repo.path, source=repo.env))
    store.insert([event(uuid4(), 1)])
    status = repo.git("status", "--porcelain", "--untracked-files=all", "--ignored=no")
    paths = {line[3:] for line in status.splitlines()}
    assert ".troupe/.gitignore" in paths
    assert any(p.startswith(".troupe/events/") and p.endswith(".jsonl") for p in paths)
    assert not any("local" in p or p.endswith(".lock") for p in paths)


# Subscriptions across processes (spec: event-store, "A subscription delivers other writers'
# events as they're recorded", "A subscription that can only poll says so", "A subscription that
# finds it missed an event says so"; watch-event-segments design D3 to D5, D7).

TIMED_WRITER = """
import sys, time
from pathlib import Path
from uuid import UUID, uuid4
sys.path.insert(0, {tests!r})
from storetesting import event
from troupe.core.vcs import load_vcs
import troupe_store_text.store as text_store

append = text_store.append_bytes

def timed(path, data, *args, **kwargs):
    result = append(path, data, *args, **kwargs)
    print("APPENDED", repr(time.time()), flush=True)
    return result

text_store.append_bytes = timed
theatre = Path({theatre!r})
store = text_store.TextStore(theatre, load_vcs("files", theatre))
stream = uuid4()
for version, _ in enumerate(sys.stdin, start=1):
    time.sleep(0.1)
    store.insert([event(stream, version)])
    print("recorded", flush=True)
"""
"""Records one event per line read, in one session (so the first creates a segment and later ones
append to it), printing the wall-clock time each segment append returned (design D7)."""

BOUND = 0.25  # seconds: a quarter of the 1 s subscription poll this replaces

STALL_SECONDS = 5.0
"""How much a loaded machine may add to a timed delivery beyond its interval: to a delivery that
happens once, which a median can't cover, and to the median of polled deliveries, where a slow
stretch can cover most of the samples (#91). One scheduling stall has taken 1.06 s in CI (#81) and
3.40 s locally; #91's slow stretch had a median of 0.52 s. Well inside the 10 s wait, which is
what fails a store that never delivers."""


class Writer:
    def __init__(self, theatre: Path) -> None:
        code = TIMED_WRITER.format(tests=TESTS, theatre=str(theatre))
        self.process = subprocess.Popen(
            [sys.executable, "-c", code],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    def record(self) -> None:
        assert self.process.stdin is not None
        self.process.stdin.write("record\n")
        self.process.stdin.flush()

    def appended_at(self) -> float:
        """When the last recording's append returned, once it has been recorded."""
        assert self.process.stdout is not None
        appended: float | None = None
        while (line := self.process.stdout.readline()) != "recorded\n":
            assert line.startswith("APPENDED "), (line, self.stderr())
            appended = float(line.split()[1])
        assert appended is not None
        return appended

    def stderr(self) -> str:
        return self.process.stderr.read() if self.process.stderr else ""

    def close(self) -> None:
        assert self.process.stdin is not None
        self.process.stdin.close()
        assert self.process.wait(timeout=30) == 0, self.stderr()


@pytest.fixture
def writer(tmp_path: Path) -> Iterator[Writer]:
    process = Writer(tmp_path)
    yield process
    process.close()


@contextmanager
def listened(store: TextStore) -> Iterator[threading.Event]:
    heard = threading.Event()
    store.listen(heard)
    try:
        yield heard
    finally:
        store.unlisten(heard)


class Silent(watching._Backend):
    """A watch that is set up but never reports, as on a file system that doesn't deliver."""

    def __init__(self) -> None:
        self._stop = threading.Event()

    def wait(self, timeout: float | None) -> bool:
        self._stop.wait(timeout)
        return False

    def interrupt(self) -> None:
        self._stop.set()

    def release(self) -> None:
        pass


def silent(directory: Path) -> DirectoryWatch:
    return DirectoryWatch(directory, Silent())


def refusing(directory: Path) -> DirectoryWatch:
    raise WatchUnavailableError(directory, "the platform refused (a test)")


def store_for(theatre: Path, **options: object) -> TextStore:
    return TextStore(theatre, load_vcs("files", theatre), **options)  # type: ignore[arg-type]


def delays(store: TextStore, heard: threading.Event, writer: Writer, count: int = 5) -> list[float]:
    """How long each of ``count`` events the writer records takes to reach the listener, from when
    its append returned. Each must arrive, and be the one event the store's order gained."""
    measured: list[float] = []
    for _ in range(count):
        before = store.max_notification_id() or 0
        heard.clear()
        writer.record()
        assert heard.wait(10)
        woke = time.time()
        measured.append(woke - writer.appended_at())
        assert store.max_notification_id() == before + 1
    return measured


class Recording:
    """What a store's subscription did (design D2 of windows-slow-stretch): each wait it made
    between polled looks, as the number of looks before it and its timeout, and each look, as when
    it started (by ``time.time()``, the clock the writer prints) and whether it delivered."""

    def __init__(self) -> None:
        self.waits: list[tuple[int, float | None]] = []
        self.looks: list[tuple[float, bool]] = []
        self._changed = threading.Condition()

    def looked(self, started: float, delivered: bool) -> None:
        with self._changed:
            self.looks.append((started, delivered))
            self._changed.notify_all()

    def wait_for_looks(self, count: int, timeout: float) -> bool:
        with self._changed:
            return self._changed.wait_for(lambda: len(self.looks) >= count, timeout)

    def wait_for_deliveries(self, count: int, timeout: float) -> bool:
        with self._changed:
            return self._changed.wait_for(lambda: len(self.deliveries()) >= count, timeout)

    def deliveries(self) -> list[int]:
        """The indexes of the looks that delivered."""
        return [index for index, (_, delivered) in enumerate(self.looks) if delivered]

    def waits_before_each_polled_look(self) -> list[int]:
        """How many waits came just before each look from the first wait on: polling waits once
        before each look."""
        if not self.waits:
            return []
        marks = [looks_before for looks_before, _ in self.waits]
        return [marks.count(look) for look in range(marks[0], len(self.looks))]

    def first_look_after(self, moment: float) -> int:
        """The index of the first look that started after ``moment``, or past the last look."""
        return next(
            (index for index, (started, _) in enumerate(self.looks) if started > moment),
            len(self.looks),
        )


def recorded(store: TextStore, monkeypatch: pytest.MonkeyPatch) -> Recording:
    """Record ``store``'s subscription from its start: call before ``listen``."""
    recording = Recording()

    class Waits(threading.Event):
        def wait(self, timeout: float | None = None) -> bool:
            recording.waits.append((len(recording.looks), timeout))
            return super().wait(timeout)

    class Subscription(store_module._Subscription):
        def __init__(self, store: TextStore) -> None:
            super().__init__(store)
            self._stopped = Waits()

    deliver = store._deliver

    def look() -> bool:
        started = time.time()
        delivered = deliver()
        recording.looked(started, delivered)
        return delivered

    monkeypatch.setattr(store_module, "_Subscription", Subscription)
    monkeypatch.setattr(store, "_deliver", look)
    return recording


@dataclass(frozen=True)
class Polled:
    appended: float
    """When the writer's append returned."""
    delay: float
    """From then until the listener woke."""
    look: int
    """The index of the recorded look that delivered it."""


def polled(
    store: TextStore, heard: threading.Event, writer: Writer, recording: Recording, count: int = 5
) -> list[Polled]:
    """Each of ``count`` events the writer records, as ``delays()`` measures them (each must arrive
    and be the one event the store's order gained), with the look that delivered it."""
    measured: list[Polled] = []
    for _ in range(count):
        before = store.max_notification_id() or 0
        delivered = len(recording.deliveries())
        heard.clear()
        writer.record()
        assert heard.wait(10)
        woke = time.time()
        appended = writer.appended_at()
        # The listener is told inside the look, before the look is recorded as delivering.
        assert recording.wait_for_deliveries(delivered + 1, 10), recording.looks
        measured.append(Polled(appended, woke - appended, recording.deliveries()[delivered]))
        assert store.max_notification_id() == before + 1
    return measured


def test_another_processs_events_each_reach_a_listener_with_a_median_delay_under_the_bound(
    tmp_path: Path, writer: Writer
) -> None:
    writer.record()  # the segment and events/ exist before listening; later events append
    writer.appended_at()
    store = store_for(tmp_path, poll_seconds=60, check_seconds=60)
    with listened(store) as heard:
        woken = delays(store, heard, writer)
    assert statistics.median(woken) < BOUND, woken


def test_the_first_event_reaches_a_listener_that_subscribed_before_events_existed(
    tmp_path: Path, writer: Writer
) -> None:
    store = store_for(tmp_path, poll_seconds=60, check_seconds=60)
    assert not store.events_dir.exists()
    with listened(store) as heard:
        writer.record()
        writer.appended_at()
        assert heard.wait(10)
        assert store.max_notification_id() == 1


def test_a_listened_store_reads_no_segment_while_nothing_is_recorded(
    tmp_path: Path, writer: Writer, monkeypatch: pytest.MonkeyPatch
) -> None:
    writer.record()
    writer.appended_at()
    store = store_for(tmp_path, poll_seconds=60, check_seconds=60)
    looks: list[float] = []
    sizes = store._sizes

    def counted() -> dict[str, int]:
        looks.append(time.monotonic())
        return sizes()

    monkeypatch.setattr(store, "_sizes", counted)
    with listened(store):
        time.sleep(2.0)  # listening reads once, and a fresh watch may wake spuriously for 1.5 s
        looks.clear()
        time.sleep(2)
        assert looks == []


def test_a_refused_watch_falls_back_to_an_announced_poll_at_its_interval_and_delivers_at_next_look(
    tmp_path: Path, writer: Writer, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = store_for(tmp_path, poll_seconds=0.2, check_seconds=60, watcher=refusing)
    recording = recorded(store, monkeypatch)
    with listened(store) as heard:
        [notice] = [n for n in store.notices() if n.code == "events.subscription-polling"]
        assert notice.details["reason"] == "watch-refused"
        assert "the platform refused (a test)" in notice.details["detail"]
        assert notice.path == str(store.events_dir.absolute())
        check_notice(notice.to_data())
        events = polled(store, heard, writer, recording)
        waits = recording.waits_before_each_polled_look()
        assert len(waits) >= 5, (recording.waits, recording.looks)
        assert set(waits) == {1}, (recording.waits, recording.looks)
        assert {timeout for _, timeout in recording.waits} == {0.2}, recording.waits
        for event in events:
            assert event.look <= recording.first_look_after(event.appended), (
                event,
                recording.looks,
            )
        assert statistics.median(e.delay for e in events) < 0.2 + STALL_SECONDS, events
        codes = [n.code for n in store.notices()]
        assert codes.count("events.subscription-polling") == 1  # it lasts as the polling does
    assert "events.subscription-polling" not in [n.code for n in store.notices()]


def test_a_watch_that_never_reports_is_caught_by_the_check_then_the_store_polls(
    tmp_path: Path, writer: Writer, monkeypatch: pytest.MonkeyPatch
) -> None:
    writer.record()
    writer.appended_at()
    store = store_for(tmp_path, poll_seconds=0.2, check_seconds=1.0, watcher=silent)
    recording = recorded(store, monkeypatch)
    with listened(store) as heard:
        assert "events.subscription-polling" not in [n.code for n in store.notices()]
        # The subscription delivers once as it starts, for writes made while its watch was set up.
        # Recording before that has run would let it deliver this event, and no check would miss it.
        assert recording.wait_for_looks(1, 5), "the subscription never made its start-up delivery"
        writer.record()
        appended = writer.appended_at()
        assert heard.wait(10)
        assert time.time() - appended < 1.0 + STALL_SECONDS  # only the check can deliver it
        # The event is delivered at once; the store falls back once the watch has had a grace
        # period to report it late.
        deadline = time.monotonic() + 5
        while not (
            polling := [n for n in store.notices() if n.code == "events.subscription-polling"]
        ):
            assert time.monotonic() < deadline, "the store never said it was polling"
            time.sleep(0.1)
        [notice] = polling
        assert notice.details["reason"] == "watch-missed-write"
        check_notice(notice.to_data())
        events = polled(store, heard, writer, recording)
        waits = recording.waits_before_each_polled_look()
        assert len(waits) >= 5, (recording.waits, recording.looks)
        assert set(waits) == {1}, (recording.waits, recording.looks)
        assert {timeout for _, timeout in recording.waits} == {0.2}, recording.waits
        for event in events:
            assert event.look <= recording.first_look_after(event.appended), (
                event,
                recording.looks,
            )
        assert statistics.median(e.delay for e in events) < 0.2 + STALL_SECONDS, events


class Manual(watching._Backend):
    """A watch that reports a change only when the test says so."""

    def __init__(self) -> None:
        self.reported = threading.Event()
        self._stopped = False

    def wait(self, timeout: float | None) -> bool:
        changed = self.reported.wait(timeout)
        self.reported.clear()
        return changed and not self._stopped

    def interrupt(self) -> None:
        self._stopped = True
        self.reported.set()

    def release(self) -> None:
        pass


def test_a_watch_that_reports_an_event_just_after_a_check_found_it_isnt_counted_as_missing(
    tmp_path: Path, writer: Writer
) -> None:
    writer.record()
    writer.appended_at()
    manual = Manual()
    store = store_for(
        tmp_path,
        poll_seconds=60,
        check_seconds=0.5,
        watcher=lambda directory: DirectoryWatch(directory, manual),
    )
    with listened(store) as heard:
        time.sleep(0.2)
        heard.clear()
        writer.record()
        writer.appended_at()
        assert heard.wait(5)  # the check found it before the watch reported it
        manual.reported.set()  # the notification arrives late, within the grace period
        time.sleep(1.5)
        assert "events.subscription-polling" not in [n.code for n in store.notices()]


def test_an_event_recorded_while_the_watch_is_being_set_up_reaches_the_listener_at_once(
    tmp_path: Path,
) -> None:
    other = store_for(tmp_path)  # another session, as another process would be
    other.insert([event(uuid4(), 1)])

    def recording_first(directory: Path) -> DirectoryWatch:
        other.insert([event(uuid4(), 1)])  # after the listener's read, before its watch
        # A watch that never reports: some platforms also report a write made just before a
        # watch starts, which would hide a store that doesn't look again once it is watching.
        return DirectoryWatch(directory, Manual())

    store = store_for(tmp_path, poll_seconds=60, check_seconds=60, watcher=recording_first)
    with listened(store) as heard:
        assert heard.wait(2)
        assert store.max_notification_id() == 2
        assert "events.subscription-polling" not in [n.code for n in store.notices()]
