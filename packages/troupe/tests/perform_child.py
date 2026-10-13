"""Runs perform in its own process, for tests that kill it mid-run or read its run from another
process. Arguments: the theatre's path, its isolated git environment as JSON, and the perform
request as JSON. Prints ``STARTED <run id>`` once the run's first event is recorded.

An optional fourth argument names a file outside the theatre. For each segment append, the moment
it returns, a line is added to it: the wall-clock time, then the seq of each run event the append
wrote (watch-event-segments design D7: delays are timed from the write, not from the event's at).
"""

import json
import re
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import troupe_store_text.store as text_store
from gitrepo import Repo
from runtesting import Harness
from troupe.core.messages import Message


class Announcing(Harness):
    def send(self, update: Message) -> None:
        data: dict[str, Any] = update.to_data()
        if data["kind"] == "event" and data["seq"] == 0:
            print(f"STARTED {data['runId']}", flush=True)


SEQ = re.compile(rb'"seq":(\d+)')


def reported_seqs(data: bytes) -> list[int]:
    """The seq of each run event in appended lines (a line's keys are sorted, so its state, which
    holds the seq, comes before its topic)."""
    return [
        int(found.group(1))
        for line in data.splitlines()
        if b"Run.Reported" in line and (found := SEQ.search(line))
    ]


def time_appends(side: Path) -> None:
    # The store's own reference to the platform's append, replaced where the store looks it up.
    append: Callable[[Path, bytes], int] = vars(text_store)["append_bytes"]

    def timed(path: Path, data: bytes) -> int:
        result = append(path, data)
        appended = time.time()
        seqs = reported_seqs(data)
        with side.open("a", encoding="utf-8") as out:
            out.write(" ".join([repr(appended), *map(str, seqs)]) + "\n")
        return result

    vars(text_store)["append_bytes"] = timed


def main() -> None:
    path, env, request = sys.argv[1], json.loads(sys.argv[2]), json.loads(sys.argv[3])
    if len(sys.argv) > 4:
        time_appends(Path(sys.argv[4]))
    result = Announcing(Repo(Path(path), env)).perform(request)
    print(f"ENDED {result.run.outcome}", flush=True)


if __name__ == "__main__":
    main()
