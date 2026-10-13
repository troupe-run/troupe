"""Another process, for test_platform_watching: changes files, or watches a directory.

``python watch_child.py`` reads one command per line from standard input, waits 0.1 s so the test
is already waiting, carries it out, and prints ``DONE <time.time()>`` the moment it returns:
- ``append <path>`` appends a line through troupe.platform.files.append_bytes;
- ``create <path>`` creates an empty file;
- ``remove <path>`` removes a file.

``python watch_child.py watch <directory> <limit>`` first lowers its own limit on open files to
<limit> (Linux and macOS), then watches <directory>, prints READY, and prints CHANGED or QUIET
after one wait of up to 10 s.
"""

import sys
import time
from pathlib import Path

from troupe.platform.files import append_bytes
from troupe.platform.watching import watch


def change() -> None:
    for line in sys.stdin:
        command, _, argument = line.strip().partition(" ")
        path = Path(argument)
        time.sleep(0.1)
        if command == "append":
            append_bytes(path, b'{"line":1}\n')
        elif command == "create":
            path.touch()
        elif command == "remove":
            path.unlink()
        else:
            sys.exit(f"unknown command {command!r}")
        print(f"DONE {time.time()!r}", flush=True)


def watch_with_limit(directory: Path, limit: int) -> None:
    if sys.platform != "win32":
        import resource

        _, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        resource.setrlimit(resource.RLIMIT_NOFILE, (limit, hard))
    with watch(directory) as watching:
        while watching.wait(0.3):
            pass  # a directory made just before the watch may give one spurious wake
        print("READY", flush=True)
        print("CHANGED" if watching.wait(10) else "QUIET", flush=True)


if __name__ == "__main__":
    if sys.argv[1:2] == ["watch"]:
        watch_with_limit(Path(sys.argv[2]), int(sys.argv[3]))
    else:
        change()
