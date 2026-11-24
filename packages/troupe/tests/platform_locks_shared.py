"""Helpers that test_platform_locks.py shares with other test modules."""

import subprocess
import sys
import textwrap
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

HOLDER = textwrap.dedent(
    """
    import sys
    from troupe.platform.locks import hold
    with hold(sys.argv[1], timeout=10.0, announce_after=10.0):
        print("locked", flush=True)
        sys.stdin.read()
    """
)


@contextmanager
def held_by_another_process(directory: Path) -> Iterator[subprocess.Popen[str]]:
    holder = subprocess.Popen(
        [sys.executable, "-c", HOLDER, str(directory)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    assert holder.stdout is not None
    assert holder.stdin is not None
    try:
        assert holder.stdout.readline().strip() == "locked"
        yield holder
    finally:
        if holder.poll() is None:
            holder.stdin.close()
        holder.wait(timeout=10)
