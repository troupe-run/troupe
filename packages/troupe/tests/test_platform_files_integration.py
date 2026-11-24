"""Tests for atomic file replacement (spec: platform).

Its tests that stay in their own process are in unit/test_platform_files.py."""

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from platform_files_shared import WINDOWS, _only_the_target_is_left
from troupe.core import files as core_files
from troupe.core.errors import TroupeError
from troupe.platform import files

# Requirement: Atomic file replacement - "Reader never sees a partial write"

WRITER = textwrap.dedent(
    """
    import sys
    from troupe.platform.files import replace_bytes
    target, rounds = sys.argv[1], int(sys.argv[2])
    versions = [b"a" * 2_000_000, b"b" * 1_000_000]
    for round in range(rounds):
        replace_bytes(target, versions[round % 2], timeout=10.0, announce_after=10.0)
    """
)


def test_a_reader_never_sees_a_partial_write(tmp_path: Path) -> None:
    target = tmp_path / "big.yml"
    versions = {b"a" * 2_000_000, b"b" * 1_000_000}
    target.write_bytes(b"b" * 1_000_000)
    writer = subprocess.Popen([sys.executable, "-c", WRITER, str(target), "60"])
    reads = 0
    try:
        while writer.poll() is None:
            content = files.read_bytes(target, timeout=5.0, announce_after=5.0)
            assert content in versions, f"read {len(content)} bytes, not a complete version"
            reads += 1
    finally:
        writer.wait(timeout=60)
    assert writer.returncode == 0
    assert reads > 0


# Requirement: Replacing a file that is open elsewhere is bounded and announced

HOLDER = textwrap.dedent(
    """
    import sys
    handle = open(sys.argv[1], "rb")
    print("open", flush=True)
    sys.stdin.read()
    handle.close()
    """
)


def test_replacing_a_file_another_process_holds_open(tmp_path: Path) -> None:
    """Windows can't replace a file another process has open: troupe waits, announces, then
    fails with an error naming the path. POSIX can, so the replacement succeeds at once."""
    target = tmp_path / "held.yml"
    target.write_bytes(b"original\n")
    holder = subprocess.Popen(
        [sys.executable, "-c", HOLDER, str(target)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    assert holder.stdout is not None
    assert holder.stdin is not None
    try:
        assert holder.stdout.readline().strip() == "open"
        waits: list[tuple[Path, float]] = []
        if WINDOWS:
            with pytest.raises(TroupeError) as caught:
                core_files.replace_file(
                    target,
                    b"new\n",
                    timeout=0.6,
                    announce_after=0.1,
                    on_wait=lambda p, w: waits.append((p, w)),
                )
            assert caught.value.code == "replace.in-use"
            assert caught.value.path == str(target)
            assert [path for path, _ in waits] == [target]
            assert target.read_bytes() == b"original\n"
            _only_the_target_is_left(tmp_path, target)
        else:
            core_files.replace_file(
                target,
                b"new\n",
                timeout=0.6,
                announce_after=0.1,
                on_wait=lambda p, w: waits.append((p, w)),
            )
            assert waits == []
            assert target.read_bytes() == b"new\n"
    finally:
        holder.stdin.close()
        holder.wait(timeout=10)
