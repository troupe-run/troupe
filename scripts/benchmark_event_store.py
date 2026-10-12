"""Measure how long the text event store takes to open a theatre cold (event-store design D4).

Usage: uv run scripts/benchmark_event_store.py [segments]

Writes ``segments`` segments (10,000 by default), one batch of one event each, as that many
recording commands would, into a temporary theatre with no version control. Then it times, each
in a new store as a new troupe process would:

- the first read, which reads every segment and writes the local notification order;
- a later read, which reads every segment and finds the order already written.

docs/event-store.md records the result, so the file count is judged on a number.
"""

import shutil
import sys
import tempfile
import time
from pathlib import Path
from uuid import uuid4

from troupe.core import strict_json
from troupe.core.ulid import new_ulid
from troupe.core.vcs import load_vcs
from troupe_store_text.codec import Header, encode_event, encode_header
from troupe_store_text.store import TextStore


def write_segments(theatre: Path, count: int) -> None:
    events = theatre / ".troupe" / "events"
    events.mkdir(parents=True)
    for n in range(count):
        session = new_ulid()
        state = strict_json.dumps({"n": n, "timestamp": "2026-10-12T00:00:00Z"}).encode()
        _, line = encode_event(uuid4(), 1, "bench:Recorded", (), state, (new_ulid(), 0, 1))
        header = encode_header(Header(session=session, vcs="files", branch=None))
        (events / f"{session}.jsonl").write_bytes(header + line)


def timed_read(theatre: Path) -> tuple[float, int]:
    started = time.perf_counter()
    store = TextStore(theatre, load_vcs("files", theatre))
    count = store.max_notification_id() or 0
    return time.perf_counter() - started, count


def main() -> None:
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 10_000
    theatre = Path(tempfile.mkdtemp(prefix="troupe-bench-"))
    try:
        write_segments(theatre, count)
        first, ordered = timed_read(theatre)
        later, _ = timed_read(theatre)
        print(
            f"{count} segments, {ordered} events ({sys.platform}, Python {sys.version.split()[0]})"
        )
        print(f"first read (orders every event): {first:.2f}s")
        print(f"later read (order already written): {later:.2f}s")
    finally:
        shutil.rmtree(theatre, ignore_errors=True)


if __name__ == "__main__":
    main()
