"""Accepts or discards a run's changes in its own process, for tests of two at once. Arguments: the
theatre's path, its isolated git environment as JSON, ``accept`` or ``discard``, and the run id.
Prints ``OK`` or the error's code."""

import asyncio
import json
import sys
from pathlib import Path

from gitrepo import Repo
from runtesting import Harness
from troupe.core.client import messages as m
from troupe.core.errors import TroupeError
from troupe.core.runs.changes import accept, discard


def main() -> None:
    path, env, what, run_id = sys.argv[1], json.loads(sys.argv[2]), sys.argv[3], sys.argv[4]
    harness = Harness(Repo(Path(path), env))
    try:
        if what == "accept":
            asyncio.run(
                accept(
                    m.AcceptRequest(run=run_id),
                    harness.session(),
                    harness.send,
                    backends=harness.backends(),
                )
            )
        else:
            asyncio.run(
                discard(
                    m.DiscardRequest(run=run_id),
                    harness.session(),
                    harness.send,
                    backends=harness.backends(),
                )
            )
    except TroupeError as error:
        print(error.code, flush=True)
        return
    print("OK", flush=True)


if __name__ == "__main__":
    main()
