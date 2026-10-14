"""Stopping a subscription (spec: event-store, "A stopped subscription leaves the store alone";
stopped-event-store design D1 to D4, #97)."""

import threading
import time
from pathlib import Path
from uuid import uuid4

import pytest

from protocol_schemas import check_error
from storetesting import event, fresh_store, snapshot
from troupe.core.errors import TroupeError
from troupe.core.vcs import load_vcs
from troupe_store_text.store import TextStore, _Subscription


def _store(theatre: Path) -> TextStore:
    # The poll and the check are far longer than any test here, so neither runs on its own.
    return TextStore(theatre, load_vcs("files", theatre), poll_seconds=60, check_seconds=60)


def test_a_subscription_stopped_before_its_first_delivery_has_ended_and_wrote_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path)
    store.insert([event(uuid4(), 1)])
    threads: list[threading.Thread] = []
    run = _Subscription._run

    def late(self: _Subscription) -> None:
        threads.append(threading.current_thread())
        self._stopped.wait(timeout=10)  # its first delivery comes after the stop, as in #97
        run(self)

    monkeypatch.setattr(_Subscription, "_run", late)
    listener = threading.Event()
    store.listen(listener)
    # Another writer's event, which this store hasn't ordered: the first delivery would order it.
    fresh_store(tmp_path).insert([event(uuid4(), 1)])
    before = snapshot(tmp_path)
    try:
        store.unlisten(listener)
        (thread,) = threads
        assert not thread.is_alive(), "the subscription's thread was still running after the stop"
        time.sleep(1.0)
        assert snapshot(tmp_path) == before
        assert not listener.is_set()
    finally:
        for thread in threads:
            thread.join(timeout=5)


def test_a_stop_during_a_delivery_returns_only_once_the_delivery_and_the_thread_have_ended(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path)
    store.insert([event(uuid4(), 1)])
    entered, proceed = threading.Event(), threading.Event()
    threads: list[threading.Thread] = []
    read = TextStore.max_notification_id

    def held(self: TextStore) -> int | None:
        if threading.current_thread().name == "troupe-subscription":
            threads.append(threading.current_thread())
            entered.set()
            proceed.wait(timeout=10)
        return read(self)

    monkeypatch.setattr(TextStore, "max_notification_id", held)
    listener = threading.Event()
    store.listen(listener)  # the thread's start-up delivery reads the order, and is held there
    try:
        assert entered.wait(timeout=10), "the subscription never started its first delivery"
        stopping = threading.Thread(target=store.unlisten, args=(listener,), daemon=True)
        stopping.start()
        stopping.join(timeout=0.2)
        assert stopping.is_alive(), "the stop returned while a delivery was still in progress"
        proceed.set()
        stopping.join(timeout=2)
        assert not stopping.is_alive(), "the stop didn't return once the delivery had ended"
        assert not any(thread.is_alive() for thread in threads)
    finally:
        proceed.set()


def test_a_thread_that_does_not_end_is_announced_once_then_fails_the_stop_at_the_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    release = threading.Event()

    def stuck(self: _Subscription) -> None:
        release.wait(timeout=30)

    monkeypatch.setattr(_Subscription, "_run", stuck)
    waits: list[tuple[Path, float]] = []
    store = TextStore(
        tmp_path,
        load_vcs("files", tmp_path),
        poll_seconds=60,
        check_seconds=60,
        stop_timeout=0.5,
        lock_announce_after=0.1,
        on_wait=lambda path, waited: waits.append((path, waited)),
    )
    listener = threading.Event()
    store.listen(listener)
    try:
        started = time.monotonic()
        with pytest.raises(TroupeError) as raised:
            store.unlisten(listener)
        elapsed = time.monotonic() - started
    finally:
        release.set()
    error = raised.value
    assert error.code == "events.subscription-not-stopped"
    assert 0.5 <= elapsed < 0.5 + 2.0
    assert [path for path, _ in waits] == [store.events_dir]
    assert 0.1 <= waits[0][1] < 0.5
    assert error.path == str(store.events_dir.absolute())
    assert error.details["limitSeconds"] == 0.5
    check_error(error.to_data())
