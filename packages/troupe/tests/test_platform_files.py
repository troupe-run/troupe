"""Tests for atomic file replacement (spec: platform)."""

import os
import stat
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from hypothesis import example, given, settings
from hypothesis import strategies as st

from troupe.core import files as core_files
from troupe.core.errors import TroupeError
from troupe.platform import files
from troupe.platform.errors import FileInUseError

WINDOWS = sys.platform == "win32"


def _only_the_target_is_left(directory: Path, target: Path) -> None:
    assert sorted(directory.iterdir()) == [target]


# Requirement: Atomic file replacement


@settings(max_examples=60, deadline=None)
@given(data=st.binary(max_size=4096))
@example(data=b"")
@example(data=b"\xef\xbb\xbfkey: value\r\nother: 1\r\n")
@example(data=b"no final newline")
@example(data=b"tab\there\x00nul")
def test_replacement_writes_exactly_the_given_bytes(
    tmp_path_factory: pytest.TempPathFactory, data: bytes
) -> None:
    directory = tmp_path_factory.mktemp("replace")
    target = directory / "troupe.yml"
    target.write_bytes(b"old contents\n")
    files.replace_bytes(target, data, timeout=2.0, announce_after=1.0)
    assert target.read_bytes() == data
    _only_the_target_is_left(directory, target)


def test_replacing_a_missing_file_creates_it(tmp_path: Path) -> None:
    target = tmp_path / "new.yml"
    files.replace_bytes(target, b"created\n", timeout=2.0, announce_after=1.0)
    assert target.read_bytes() == b"created\n"
    _only_the_target_is_left(tmp_path, target)


# Windows keeps only the read-only flag, so its permission modes are 0o444 and 0o666.
MODES = [0o444, 0o666] if WINDOWS else [0o640, 0o600, 0o444, 0o755]


@pytest.mark.parametrize("mode", MODES, ids=oct)
def test_replacement_keeps_the_original_permission_bits(tmp_path: Path, mode: int) -> None:
    target = tmp_path / "config.yml"
    target.write_bytes(b"before\n")
    os.chmod(target, mode)
    try:
        files.replace_bytes(target, b"after\n", timeout=2.0, announce_after=1.0)
        assert stat.S_IMODE(target.stat().st_mode) == mode
        assert target.read_bytes() == b"after\n"
    finally:
        os.chmod(target, 0o644)


# Requirement: A failed replacement changes nothing


@pytest.mark.parametrize("failing", ["fsync", "replace"])
def test_a_replacement_that_fails_part_way_leaves_the_original_and_no_temporary_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failing: str
) -> None:
    target = tmp_path / "config.yml"
    target.write_bytes(b"original\n")

    def fail(*args: object, **kwargs: object) -> None:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(os, failing, fail)
    with pytest.raises(TroupeError) as caught:
        core_files.replace_file(target, b"new contents\n", timeout=1.0, announce_after=0.5)
    monkeypatch.undo()
    assert caught.value.code == "replace.failed"
    assert target.read_bytes() == b"original\n"
    _only_the_target_is_left(tmp_path, target)


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


# Moving a finished temporary file into place (content-addressed files; spec: artifact-store)


def test_commit_file_moves_the_temporary_file_to_a_new_target(tmp_path: Path) -> None:
    temp = tmp_path / "tmp.part"
    temp.write_bytes(b"artifact")
    target = tmp_path / "ab" / "abcdef"
    target.parent.mkdir()
    assert files.commit_file(temp, target, timeout=2.0, announce_after=1.0) is True
    assert target.read_bytes() == b"artifact"
    assert not temp.exists()


def test_commit_file_keeps_an_existing_target_and_removes_the_temporary_file(
    tmp_path: Path,
) -> None:
    temp = tmp_path / "tmp.part"
    temp.write_bytes(b"artifact")
    target = tmp_path / "abcdef"
    target.write_bytes(b"artifact")
    assert files.commit_file(temp, target, timeout=2.0, announce_after=1.0) is False
    assert target.read_bytes() == b"artifact"
    assert not temp.exists()


def test_commit_file_does_not_wait_for_an_existing_target_held_open_by_a_reader(
    tmp_path: Path,
) -> None:
    temp = tmp_path / "tmp.part"
    temp.write_bytes(b"artifact")
    target = tmp_path / "abcdef"
    target.write_bytes(b"artifact")
    waits: list[float] = []
    with target.open("rb"):
        assert (
            files.commit_file(
                temp,
                target,
                timeout=0.5,
                announce_after=0.0,
                on_wait=lambda _path, waited: waits.append(waited),
            )
            is False
        )
    assert waits == []
    assert not temp.exists()


def test_a_file_held_open_elsewhere_is_replace_in_use_naming_the_wait_on_every_platform(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Only Windows holds a file open against replacement, so the platform's answer is stood in
    # for here; the Windows-only test above checks the platform really gives it.
    def held(path: Path, *_: object, **__: object) -> None:
        raise FileInUseError(Path(path), 2.5)

    monkeypatch.setattr(files, "replace_bytes", held)
    monkeypatch.setattr(files, "read_bytes", held)
    target = tmp_path / "held.txt"
    for attempt in (
        lambda: core_files.replace_file(target, b"x"),
        lambda: core_files.read_file(target),
    ):
        with pytest.raises(TroupeError) as caught:
            attempt()
        assert caught.value.code == "replace.in-use"
        assert caught.value.details == {"waitedSeconds": 2.5}
