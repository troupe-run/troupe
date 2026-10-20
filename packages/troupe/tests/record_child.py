"""Records events from one long-lived EventStore, for tests that move git in another process
between events (test_event_service; cache-vcs-state design D7 test 8). Arguments: the theatre's path
and its isolated git environment as JSON.

Prints READY once the store is open, then, for each line it reads on stdin, records one event and
prints ``RECORDED <event id>``. It ends at the end of its input.
"""

import json
import sys
from pathlib import Path

from gitrepo import Repo
from storetesting import Counter, git_service


def main() -> None:
    path, env = Path(sys.argv[1]), json.loads(sys.argv[2])
    service = git_service(Repo(path, env))  # the real clock and the default racy windows
    print("READY", flush=True)
    for value, _ in enumerate(sys.stdin):
        [recorded] = service.command(via="cli").record(Counter(value=value).collect_events())
        print(f"RECORDED {recorded.event_id}", flush=True)


if __name__ == "__main__":
    main()
