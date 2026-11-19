"""Several stores on one theatre, in one process or several (spec: event-store, "Notification IDs
are local, dense and never renumbered" and "Followers' positions are local"; troupe-run/troupe#450).

Each store keeps the local order and tracking logs in memory. These tests check that a store sees
what another store wrote to them before it relies on its own copy, so no notification id is
appended twice and no follower's position goes backwards.
"""

import shutil
import subprocess
import sys
import tempfile
import threading
from collections.abc import Iterator
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from eventsourcing.persistence import IntegrityError, Notification, Tracking
from hypothesis import HealthCheck, settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, rule

from storetesting import event, fresh_store
from troupe.core import defaults, strict_json
from troupe.core.errors import TroupeError
from troupe.core.files import replace_file
from troupe.core.notices import Notice
from troupe_store_text.local import OrderLog
from troupe_store_text.recorders import TextApplicationRecorder
from troupe_store_text.store import TextStore

TESTS = str(Path(__file__).resolve().parents[2] / "troupe" / "tests")

CHILD = """
import sys
from pathlib import Path
from uuid import UUID
sys.path.insert(0, {tests!r})
from storetesting import event, fresh_store
store = fresh_store(Path({theatre!r}))
store.insert([event(UUID({stream!r}), {version})])
"""


def order_file(theatre: Path) -> Path:
    (path,) = (theatre / ".troupe" / "local" / "order").glob("*.jsonl")
    return path


def order_lines(theatre: Path) -> list[str]:
    return order_file(theatre).read_text().splitlines()


def write_order(theatre: Path, epoch: str, lines: list[dict[str, object]], after: int = 0) -> None:
    """Write the order file by hand, as stores before #450 was fixed could leave it. Atomically,
    so a subscription reading meanwhile sees the old file or the new one, never half of one, and
    through troupe's replace, which waits while another thread has the file open (Windows)."""
    rows = [{"epoch": epoch, "after": after}, *lines]
    replace_file(order_file(theatre), b"".join(strict_json.dumps(r).encode() + b"\n" for r in rows))


def notices(store: TextStore, code: str) -> list[Notice]:
    return [n for n in store.notices() if n.code == code]


def recorded(theatre: Path, count: int) -> tuple[str, list[str]]:
    """``count`` events recorded on a theatre, in order, and the order's epoch."""
    store = fresh_store(theatre)
    for _ in range(count):
        store.insert([event(uuid4(), 1)])
    order = OrderLog.load(order_file(theatre))
    return order.epoch, order.ids


def ordered(store: TextStore) -> list[tuple[int, str]]:
    return [(n, record.id) for n, record in store.notifications(1, 100_000, None, ())]


def test_two_stores_taking_turns_in_one_process_give_each_event_one_notification_id(
    tmp_path: Path,
) -> None:
    # The issue's repro: b reads after each of a's writes, and orders a's events again.
    a, b = fresh_store(tmp_path), fresh_store(tmp_path)
    stream = uuid4()
    a.insert([event(stream, 1)])
    b.max_notification_id()
    for version in (2, 3):
        a.insert([event(stream, version)])
        b.max_notification_id()
    later = fresh_store(tmp_path)
    assert later.max_notification_id() == 3
    assert ordered(a) == ordered(b) == ordered(later)
    assert len(order_lines(tmp_path)) == 4  # the epoch, then one line per event


def test_a_store_records_after_another_processes_events_without_reusing_their_ids(
    tmp_path: Path,
) -> None:
    store = fresh_store(tmp_path)
    stream = uuid4()
    store.insert([event(stream, 1)])
    for version in (2, 4):
        child = CHILD.format(
            tests=TESTS, theatre=str(tmp_path), stream=str(stream), version=version
        )
        subprocess.run([sys.executable, "-c", child], check=True, timeout=60)
        store.insert([event(stream, version + 1)])
    later = fresh_store(tmp_path)
    assert later.max_notification_id() == 5
    assert ordered(store) == ordered(later)


def test_a_position_recorded_by_another_store_refuses_one_that_isnt_greater(
    tmp_path: Path,
) -> None:
    a, b = fresh_store(tmp_path), fresh_store(tmp_path)
    a.insert([event(uuid4(), 1)])
    assert b.max_tracking_id("follower") is None
    a.insert_tracking(Tracking("follower", 5))
    assert b.max_tracking_id("follower") == 5
    with pytest.raises(IntegrityError, match="not greater than 5"):
        b.insert_tracking(Tracking("follower", 3))


def test_a_stale_store_never_gives_ids_to_events_in_another_order(tmp_path: Path) -> None:
    # The probe from #450: c and b number their own events 2 and 3; a, which last read the order
    # before either, would number them again by session, the other way round, so live processes
    # named different events by one id.
    a, b, c = fresh_store(tmp_path), fresh_store(tmp_path), fresh_store(tmp_path)
    b.insert([event(uuid4(), 1)])  # b's segment is older than c's
    a.max_notification_id()
    c.max_notification_id()
    c.insert([event(uuid4(), 1)])
    b.insert([event(uuid4(), 1)])
    a.max_notification_id()
    later = fresh_store(tmp_path)
    assert later.max_notification_id() == 3
    assert ordered(a) == ordered(b) == ordered(c) == ordered(later)
    assert len(order_lines(tmp_path)) == 4


def test_an_order_with_repeated_lines_is_repaired_keeping_its_epoch_and_followers(
    tmp_path: Path,
) -> None:
    epoch, ids = recorded(tmp_path, 3)
    fresh_store(tmp_path).insert_tracking(Tracking("follower", 2))
    # The damage #450 shows: lines 2 and 3 written twice.
    write_order(
        tmp_path,
        epoch,
        [
            {"n": 1, "event": ids[0]},
            {"n": 2, "event": ids[1]},
            {"n": 2, "event": ids[1]},
            {"n": 3, "event": ids[2]},
            {"n": 3, "event": ids[2]},
        ],
    )
    store = fresh_store(tmp_path)
    assert [record_id for _, record_id in ordered(store)] == ids
    (notice,) = notices(store, "events.order-repaired")
    assert notice.details == {"repeats": 2}
    assert OrderLog.load(order_file(tmp_path)).epoch == epoch
    assert len(order_lines(tmp_path)) == 4
    assert store.max_tracking_id("follower") == 2
    assert notices(store, "events.order-rebuilt") == []


CONFLICT_LINE = {  # the file's line (the epoch is line 1) where each shape is found
    "one id for two events": 4,
    "an event with two ids": 4,
    "a skipped id": 3,
    "a second epoch": 3,
}


def _conflicts(ids: list[str]) -> dict[str, list[dict[str, object]]]:
    a, b, c = ids
    return {
        "one id for two events": [{"n": 1, "event": a}, {"n": 2, "event": b}, {"n": 2, "event": c}],
        "an event with two ids": [{"n": 1, "event": a}, {"n": 2, "event": b}, {"n": 3, "event": b}],
        "a skipped id": [{"n": 1, "event": a}, {"n": 3, "event": b}],
        "a second epoch": [
            {"n": 1, "event": a},
            {"epoch": "f" * 32, "after": 0},
            {"n": 2, "event": b},
        ],
    }


@pytest.mark.parametrize("shape", sorted(CONFLICT_LINE))
def test_a_conflicting_order_is_rebuilt_under_a_new_epoch_and_followers_start_again(
    tmp_path: Path, shape: str
) -> None:
    epoch, ids = recorded(tmp_path, 3)
    fresh_store(tmp_path).insert_tracking(Tracking("follower", 2))
    write_order(tmp_path, epoch, _conflicts(ids)[shape])
    store = fresh_store(tmp_path)
    numbers = [n for n, _ in ordered(store)]
    assert numbers == list(range(numbers[0], numbers[0] + 3))
    assert numbers[0] > 3  # no id is reused (troupe-run/troupe#454)
    assert sorted(record_id for _, record_id in ordered(store)) == sorted(ids)
    (notice,) = notices(store, "events.order-rebuilt")
    assert notice.details is not None
    assert set(notice.details) == {"line", "conflict"}
    assert notice.details["line"] == CONFLICT_LINE[shape]
    assert OrderLog.load(order_file(tmp_path)).epoch != epoch
    assert store.max_tracking_id("follower") is None
    assert ordered(fresh_store(tmp_path)) == ordered(store)


def test_a_follower_mid_stream_across_a_rebuild_starts_again_from_the_rebuilt_orders_first_id(
    tmp_path: Path,
) -> None:
    epoch, ids = recorded(tmp_path, 3)
    follower = fresh_store(tmp_path)
    assert [n for n, _ in follower.notifications(1, 2, None, ())] == [1, 2]
    follower.insert_tracking(Tracking("follower", 2))
    write_order(tmp_path, epoch, _conflicts(ids)["one id for two events"])
    fresh_store(tmp_path).max_notification_id()  # another process finds the conflict, rebuilds
    assert follower.max_tracking_id("follower") is None
    first, *_ = again = [n for n, _ in follower.notifications(1, 100, None, ())]
    assert (again, first > 3) == (list(range(first, first + 3)), True)
    follower.insert_tracking(Tracking("follower", first))  # its first position under the new epoch
    assert fresh_store(tmp_path).max_tracking_id("follower") == first


def test_a_position_read_before_a_rebuild_and_recorded_after_it_skips_nothing(
    tmp_path: Path,
) -> None:
    # troupe-run/troupe#454: the follower read 1..2 under the old epoch, and records 2 under the
    # new one. Its next read, from 3, must still give it every event of the rebuilt order.
    epoch, ids = recorded(tmp_path, 3)
    follower = fresh_store(tmp_path)
    assert [n for n, _ in follower.notifications(1, 2, None, ())] == [1, 2]
    write_order(tmp_path, epoch, _conflicts(ids)["one id for two events"])
    fresh_store(tmp_path).max_notification_id()  # another process finds the conflict, rebuilds
    follower.insert_tracking(Tracking("follower", 2))
    start = follower.max_tracking_id("follower") or 0
    given = [record.id for _, record in follower.notifications(start + 1, 100, None, ())]
    assert sorted(given) == sorted(ids)


def test_a_live_subscription_across_a_rebuild_is_given_the_rebuilt_order(tmp_path: Path) -> None:
    # The library's subscription keeps its own position in memory (troupe-run/troupe#454).
    epoch, ids = recorded(tmp_path, 3)
    store = fresh_store(tmp_path, check_seconds=0.1, poll_seconds=0.1)
    streams = {store.event(event_id).stream for event_id in ids}  # type: ignore[union-attr]
    given: list[Notification] = []
    seven = threading.Event()  # three before the rebuild, three again, and the new one

    def take(subscription: Iterator[Notification]) -> None:
        for notification in subscription:  # ends when the subscription is stopped
            given.append(notification)
            if len(given) == 7:
                seven.set()

    with TextApplicationRecorder(store).subscribe() as subscription:
        taker = threading.Thread(target=take, args=(subscription,))
        taker.start()
        try:
            for _ in range(1000):  # bounded: the first three come at once
                if len(given) >= 3:
                    break
                threading.Event().wait(0.01)
            # Damaged as another process could leave it; this store finds it and rebuilds. Only this
            # store takes the lock: a second one in this process could meet its subscription thread
            # holding it (LockAlreadyHeldError, troupe-run/troupe#450).
            write_order(tmp_path, epoch, _conflicts(ids)["one id for two events"])
            new = uuid4()
            store.insert([event(new, 1)])
            seven.wait(timeout=10)  # bounded: a subscription that skips never sends all seven
        finally:
            subscription.stop()
            taker.join(timeout=10)
    assert [n.id for n in given[:3]] == [1, 2, 3]
    after = given[3:]
    assert [n.originator_id for n in after][-1:] == [new], [n.id for n in after]
    assert {n.originator_id for n in after[:-1]} == streams, [n.id for n in after]
    assert all(n.id > 3 for n in after)


def test_a_listener_is_woken_by_a_rebuild_that_keeps_the_orders_length(tmp_path: Path) -> None:
    epoch, ids = recorded(tmp_path, 3)
    store = fresh_store(tmp_path, check_seconds=0.1, poll_seconds=0.1)
    listener = threading.Event()
    store.listen(listener)
    try:
        # One id for two events. The subscription's next check finds it and rebuilds the order:
        # the same three events, three ids, under a new epoch. Only the epoch tells it changed.
        damaged = [*_conflicts(ids)["one id for two events"], {"n": 3, "event": ids[2]}]
        write_order(tmp_path, epoch, damaged)
        assert listener.wait(timeout=10), "the listener wasn't told the order was rebuilt"
        rebuilt = OrderLog.load(order_file(tmp_path))
        assert (len(rebuilt.ids), rebuilt.epoch != epoch) == (3, True)
    finally:
        store.unlisten(listener)


def test_recording_on_a_rebuilt_order_leaves_nothing_for_the_next_delivery_to_tell(
    tmp_path: Path,
) -> None:
    # A rebuilt order starts after 0, so what listeners were told is its last id, not its length.
    # Otherwise the subscription's next delivery wakes them again for the same event, and its
    # check takes that for a write the watch missed (#464 review).
    epoch, ids = recorded(tmp_path, 3)
    store = fresh_store(tmp_path)
    write_order(tmp_path, epoch, _conflicts(ids)["one id for two events"])
    assert numbers(store)[0] > 3  # this store rebuilt it
    store.insert([event(uuid4(), 1)])  # tells its listeners here, and records that it did
    assert store._deliver() is False


def test_a_log_reads_again_whole_when_a_repair_moved_lines_it_had_read(tmp_path: Path) -> None:
    epoch, ids = recorded(tmp_path, 3)
    a, b, c = ids
    write_order(tmp_path, epoch, [{"n": 1, "event": a}, {"n": 1, "event": a}, {"n": 2, "event": b}])
    log = OrderLog.load(order_file(tmp_path))
    assert (log.ids, log.repeats) == ([a, b], 1)
    # Another store repairs it (same epoch), then numbers c: the file is as long as before, but
    # every line after the repeat has moved.
    write_order(tmp_path, epoch, [{"n": 1, "event": a}, {"n": 2, "event": b}, {"n": 3, "event": c}])
    log.catch_up(trim=False)
    assert (log.ids, log.repeats) == ([a, b, c], 0)


def tracking_file(theatre: Path) -> Path:
    (path,) = (theatre / ".troupe" / "local" / "tracking").glob("*.jsonl")
    return path


def test_a_damaged_order_line_after_valid_ones_is_refused_on_every_read(tmp_path: Path) -> None:
    recorded(tmp_path, 2)
    store = fresh_store(tmp_path)
    assert store.max_notification_id() == 2
    fresh_store(tmp_path).insert([event(uuid4(), 1)])  # line n=3, which store hasn't read yet
    good = order_file(tmp_path).read_bytes()
    with order_file(tmp_path).open("ab") as handle:
        handle.write(b'{"n":4}\n')
    for _ in range(2):
        with pytest.raises(TroupeError) as caught:
            store.max_notification_id()
        assert caught.value.code == "events.malformed-record"
    replace_file(order_file(tmp_path), good)
    assert store.max_notification_id() == 3
    assert notices(store, "events.order-repaired") == []  # n=3 wasn't taken twice


def test_a_damaged_tracking_line_after_valid_ones_is_refused_on_every_read(
    tmp_path: Path,
) -> None:
    recorded(tmp_path, 1)
    store = fresh_store(tmp_path)
    store.insert_tracking(Tracking("follower", 1))
    fresh_store(tmp_path).insert_tracking(Tracking("follower", 2))
    good = tracking_file(tmp_path).read_bytes()
    with tracking_file(tmp_path).open("ab") as handle:
        handle.write(b'{"epoch":"e"}\n')
    for _ in range(2):
        with pytest.raises(TroupeError) as caught:
            store.max_tracking_id("follower")
        assert caught.value.code == "events.malformed-record"
    replace_file(tracking_file(tmp_path), good)
    assert store.max_tracking_id("follower") == 2


def test_a_live_store_numbers_again_when_the_order_file_is_deleted_or_shortened(
    tmp_path: Path,
) -> None:
    epoch, ids = recorded(tmp_path, 3)
    store = fresh_store(tmp_path)
    assert store.max_notification_id() == 3
    order_file(tmp_path).unlink()  # the malformed-record fix: delete it and troupe rebuilds it
    assert sorted(record_id for _, record_id in ordered(store)) == sorted(ids)
    renumbered = OrderLog.load(order_file(tmp_path))
    assert (renumbered.epoch != epoch, renumbered.after >= 3) == (True, True)  # no id reused
    first = renumbered.after + 1
    write_order(
        tmp_path, renumbered.epoch, [{"n": first, "event": renumbered.ids[0]}], renumbered.after
    )
    assert ordered(store)[0] == (first, renumbered.ids[0])
    assert store.max_notification_id() == first + 2
    assert ordered(fresh_store(tmp_path)) == ordered(store)


def test_a_live_store_forgets_positions_when_the_tracking_file_is_deleted_or_shortened(
    tmp_path: Path,
) -> None:
    recorded(tmp_path, 1)
    store = fresh_store(tmp_path)
    store.insert_tracking(Tracking("follower", 1))
    store.insert_tracking(Tracking("follower", 2))
    first = tracking_file(tmp_path).read_bytes().splitlines(keepends=True)[0]
    replace_file(tracking_file(tmp_path), first)
    assert store.max_tracking_id("follower") == 1
    tracking_file(tmp_path).unlink()
    assert store.max_tracking_id("follower") is None


# The highest id issued (follower-position-epoch design D3, D4; troupe-run/troupe#454).


def issued_file(theatre: Path) -> Path:
    order = order_file(theatre)
    return order.parent.parent / "issued" / f"{order.stem}.json"


def numbers(store: TextStore) -> list[int]:
    return [n for n, _ in ordered(store)]


def test_deleting_the_order_file_renumbers_after_every_id_issued(tmp_path: Path) -> None:
    recorded(tmp_path, 3)
    order_file(tmp_path).unlink()
    again = numbers(fresh_store(tmp_path))
    assert (len(again), again[0] > 3) == (3, True)
    assert again == list(range(again[0], again[0] + 3))


def test_deleting_the_issued_file_alone_loses_nothing(tmp_path: Path) -> None:
    epoch, ids = recorded(tmp_path, 3)
    issued_file(tmp_path).unlink()
    # The line that conflicts names id 3: an id issued, even though reading stops there.
    write_order(tmp_path, epoch, _conflicts(ids)["an event with two ids"])
    again = numbers(fresh_store(tmp_path))  # rebuilt after every id the old order names
    assert again[0] > 3


def test_the_issued_mark_is_raised_before_the_order_passes_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(defaults, "ORDER_ID_RESERVE", 2)
    store = fresh_store(tmp_path)
    marks = []
    for _ in range(6):
        store.insert([event(uuid4(), 1)])
        mark = strict_json.loads(issued_file(tmp_path).read_bytes())
        assert isinstance(mark, dict)
        marks.append(mark["issued"])
    assert all(mark >= n for n, mark in enumerate(marks, start=1))
    assert len(set(marks)) < len(marks)  # raised ahead, not on every insert


def test_an_epoch_line_that_doesnt_say_where_the_order_starts_is_refused(tmp_path: Path) -> None:
    recorded(tmp_path, 1)
    path = order_file(tmp_path)
    lines = path.read_bytes().splitlines(keepends=True)
    path.write_bytes(strict_json.dumps({"epoch": "e" * 32}).encode() + b"\n" + b"".join(lines[1:]))
    with pytest.raises(TroupeError) as caught:
        fresh_store(tmp_path).max_notification_id()
    assert (caught.value.code, caught.value.path) == ("events.malformed-record", str(path))
    assert "numbering after the highest notification id it has issued" in caught.value.fix


@pytest.mark.parametrize("content", [b"{}", b'{"issued": -1}', b'{"issued": "3"}', b"3", b"{"])
def test_a_damaged_issued_file_is_refused_with_how_to_mend_it(
    tmp_path: Path, content: bytes
) -> None:
    recorded(tmp_path, 3)
    issued = issued_file(tmp_path)
    issued.write_bytes(content)
    order_file(tmp_path).unlink()  # a new order must start after the mark, so it's read
    with pytest.raises(TroupeError) as caught:
        fresh_store(tmp_path).max_notification_id()
    assert (caught.value.code, caught.value.path) == (
        "events.malformed-record",
        str(issued.absolute()),
    )
    assert '{"issued": <n>}' in caught.value.fix
    assert "must be rebuilt" in caught.value.fix


STREAMS = [UUID(int=n) for n in range(1, 4)]


class SharedTheatre(RuleBasedStateMachine):
    """Two long-lived stores on one theatre, recording and reading in any order. After every step a
    new store loads the order, and all three agree on it; ids already issued never change."""

    def __init__(self) -> None:
        super().__init__()
        self.root = Path(tempfile.mkdtemp())
        self.stores = [fresh_store(self.root), fresh_store(self.root)]
        self.issued: list[str] = []
        self.positions: dict[str, int] = {}

    def teardown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    @rule(which=st.integers(0, 1), stream=st.sampled_from(STREAMS))
    def record(self, which: int, stream: UUID) -> None:
        store = self.stores[which]
        version = max((r.version for r in store.history(stream)), default=0) + 1
        store.insert([event(stream, version)])

    @rule(which=st.integers(0, 1))
    def read(self, which: int) -> None:
        self.stores[which].max_notification_id()

    @rule(which=st.integers(0, 1), name=st.sampled_from(["x", "y"]), step=st.integers(-1, 2))
    def track(self, which: int, name: str, step: int) -> None:
        if name not in self.positions and step <= 0:
            return  # a follower's first position is a notification id, so at least 1
        current = self.positions.get(name, 0)
        try:
            self.stores[which].insert_tracking(Tracking(name, current + step))
        except IntegrityError:
            assert step <= 0
        else:
            assert step > 0
            self.positions[name] = current + step

    @invariant()
    def every_store_agrees_on_the_order(self) -> None:
        later = fresh_store(self.root)
        ids = [record_id for _, record_id in ordered(later)]
        assert ordered(self.stores[0]) == ordered(self.stores[1]) == ordered(later)
        assert len(set(ids)) == len(ids)
        assert ids[: len(self.issued)] == self.issued
        self.issued = ids
        for name, position in self.positions.items():
            assert later.max_tracking_id(name) == position


SharedTheatre.TestCase.settings = settings(
    max_examples=30,
    stateful_step_count=15,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
TestSharedTheatre = SharedTheatre.TestCase
