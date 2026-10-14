"""Stopping a subscription (spec: event-store, "A stopped subscription leaves the store alone";
stopped-event-store design D1 to D4, #97)."""

import threading
import time
from pathlib import Path
from uuid import uuid4

import pytest

from storetesting import event, fresh_store, snapshot
from troupe.core.vcs import load_vcs
from troupe_store_text.store import TextStore, _Subscription


def _store(theatre: Path) -> TextStore:
    # The poll and the check are far longer than any test here, so neither runs on its own.
    return TextStore(theatre, load_vcs("files", theatre), poll_seconds=60, check_seconds=60)


@pytest.mark.xfail(strict=True, reason="#97")
def test_a_subscription_stopped_before_its_first_delivery_has_ended_and_writes_nothing_after(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path)
    store.insert([event(uuid4(), 1)])
    threads: list[threading.Thread] = []
    run = _Subscription._run

    def late(self: _Subscription) -> None:
        threads.append(threading.current_thread())
        time.sleep(0.5)  # the stop and the next writer's event both land before the first delivery
        run(self)

    monkeypatch.setattr(_Subscription, "_run", late)
    listener = threading.Event()
    store.listen(listener)
    # Another writer's event, which this store hasn't ordered: the first delivery would order it.
    fresh_store(tmp_path).insert([event(uuid4(), 1)])
    try:
        store.unlisten(listener)
        (thread,) = threads
        assert not thread.is_alive(), "the subscription's thread was still running after the stop"
        before = snapshot(tmp_path)
        time.sleep(1.0)
        assert snapshot(tmp_path) == before
        assert not listener.is_set()
    finally:
        for thread in threads:
            thread.join(timeout=5)
