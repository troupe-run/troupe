"""Runs perform in its own process, for tests that kill it mid-run or read its run from another
process. Arguments: the theatre's path, its isolated git environment as JSON, and the perform
request as JSON. Prints ``STARTED <run id>`` once the run's first event is recorded."""

import json
import sys
from pathlib import Path
from typing import Any

from gitrepo import Repo
from runtesting import Harness
from troupe.core.messages import Message


class Announcing(Harness):
    def send(self, update: Message) -> None:
        data: dict[str, Any] = update.to_data()
        if data["kind"] == "event" and data["seq"] == 0:
            print(f"STARTED {data['runId']}", flush=True)


def main() -> None:
    path, env, request = sys.argv[1], json.loads(sys.argv[2]), json.loads(sys.argv[3])
    result = Announcing(Repo(Path(path), env)).perform(request)
    print(f"ENDED {result.run.outcome}", flush=True)


if __name__ == "__main__":
    main()
