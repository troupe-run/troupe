"""A store records events after another process has recorded to the same theatre, and gives them
notification ids after that process's ones without reusing any (spec: event-store, "Notification
IDs are local, dense and never renumbered"; troupe-run/troupe#450).

Its tests that stay in their own process are in unit/test_shared_theatre.py."""

import subprocess
import sys
from pathlib import Path
from uuid import uuid4

from shared_theatre_shared import ordered
from storetesting import event, fresh_store

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
