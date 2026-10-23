"""Tests for copy-on-write file clones (spec: platform; worktree-stage design D3)."""

import errno
import os
import stat
import sys
from pathlib import Path

import pytest

from troupe.platform import clones
from troupe.platform.errors import CloneDestinationExistsError, CloneFailedError

WINDOWS = sys.platform == "win32"
MACOS = sys.platform == "darwin"
LINUX = sys.platform == "linux"

CONTENT = b"line one\r\nline two\n\x00\xff binary tail"


def _source(directory: Path, name: str = "source.bin", data: bytes = CONTENT) -> Path:
    path = directory / name
    path.write_bytes(data)
    return path


# Requirement: A file can be cloned copy-on-write


def test_a_clone_has_the_sources_bytes(tmp_path: Path) -> None:
    source = _source(tmp_path)
    clones.clone_file(source, tmp_path / "copy.bin")
    assert (tmp_path / "copy.bin").read_bytes() == CONTENT


def test_a_clone_of_an_empty_file_is_empty(tmp_path: Path) -> None:
    source = _source(tmp_path, data=b"")
    clones.clone_file(source, tmp_path / "copy.bin")
    assert (tmp_path / "copy.bin").read_bytes() == b""


@pytest.mark.skipif(WINDOWS, reason="Windows keeps only the read-only flag, not an executable bit")
@pytest.mark.parametrize("mode", [0o755, 0o644, 0o600, 0o444], ids=oct)
def test_a_clone_keeps_the_permission_bits(tmp_path: Path, mode: int) -> None:
    source = _source(tmp_path)
    source.chmod(mode)
    clones.clone_file(source, tmp_path / "copy.bin")
    assert stat.S_IMODE((tmp_path / "copy.bin").stat().st_mode) == mode


@pytest.mark.skipif(not MACOS, reason="clonefile is macOS's; CI's macOS runners use APFS")
def test_on_macos_the_mechanism_is_clonefile(tmp_path: Path) -> None:
    assert clones.clone_file(_source(tmp_path), tmp_path / "copy.bin") == "clonefile"


@pytest.mark.skipif(not WINDOWS, reason="CopyFile2 is Windows'")
def test_on_windows_the_mechanism_is_copyfile2(tmp_path: Path) -> None:
    assert clones.clone_file(_source(tmp_path), tmp_path / "copy.bin") == "copyfile2"


@pytest.mark.skipif(not LINUX, reason="FICLONE is Linux's")
def test_on_linux_the_mechanism_is_ficlone_or_a_copy_and_the_bytes_match(tmp_path: Path) -> None:
    # CI's ext4 refuses FICLONE (copy); a Btrfs or XFS developer machine clones (ficlone).
    mechanism = clones.clone_file(_source(tmp_path), tmp_path / "copy.bin")
    assert mechanism in ("ficlone", "copy")
    assert (tmp_path / "copy.bin").read_bytes() == CONTENT


@pytest.mark.skipif(not LINUX, reason="FICLONE is Linux's")
@pytest.mark.parametrize("code", [errno.EOPNOTSUPP, errno.EXDEV, errno.EINVAL])
def test_on_linux_a_refused_ficlone_falls_back_to_a_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, code: int
) -> None:
    def refuse(fd: int, source_fd: int) -> None:
        raise OSError(code, os.strerror(code))

    monkeypatch.setattr(clones, "_ficlone", refuse)
    source = _source(tmp_path)
    source.chmod(0o750)
    assert clones.clone_file(source, tmp_path / "copy.bin") == "copy"
    assert (tmp_path / "copy.bin").read_bytes() == CONTENT
    assert stat.S_IMODE((tmp_path / "copy.bin").stat().st_mode) == 0o750


@pytest.mark.skipif(not MACOS, reason="clonefile is macOS's")
@pytest.mark.parametrize("code", [errno.ENOTSUP, errno.EXDEV])
def test_on_macos_a_refused_clonefile_falls_back_to_a_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, code: int
) -> None:
    monkeypatch.setattr(clones, "_call_clonefile", lambda source, destination: code)
    source = _source(tmp_path)
    source.chmod(0o750)
    assert clones.clone_file(source, tmp_path / "copy.bin") == "copy"
    assert (tmp_path / "copy.bin").read_bytes() == CONTENT
    assert stat.S_IMODE((tmp_path / "copy.bin").stat().st_mode) == 0o750


def _can_symlink(directory: Path) -> bool:
    try:
        (directory / "probe-link").symlink_to("probe-target")
    except OSError:
        return False  # Windows without Developer Mode or the privilege
    (directory / "probe-link").unlink()
    return True


def test_a_symbolic_link_is_cloned_as_a_link_to_the_same_target(tmp_path: Path) -> None:
    if not _can_symlink(tmp_path):
        pytest.skip("this platform account can't make symbolic links")
    link = tmp_path / "link"
    link.symlink_to("does-not-exist")  # a dangling target proves it's never read
    assert clones.clone_file(link, tmp_path / "copy") == "symlink"
    assert (tmp_path / "copy").is_symlink()
    assert os.readlink(tmp_path / "copy") == "does-not-exist"


# Requirement: A clone never overwrites


def test_cloning_onto_an_existing_file_fails_and_leaves_it_unchanged(tmp_path: Path) -> None:
    source = _source(tmp_path)
    existing = tmp_path / "copy.bin"
    existing.write_bytes(b"keep me")
    with pytest.raises(CloneDestinationExistsError) as caught:
        clones.clone_file(source, existing)
    assert caught.value.destination == existing
    assert existing.read_bytes() == b"keep me"


def test_a_clone_that_fails_part_way_leaves_no_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(source: Path, fd: int) -> None:
        os.write(fd, b"part")
        raise OSError(errno.EIO, "disk said no")

    monkeypatch.setattr(clones, "_copy_into", fail)
    # Force the copying path on every platform: clonefile and FICLONE refuse, CopyFile2 isn't used.
    monkeypatch.setattr(clones, "_PLATFORM", "unknown")
    with pytest.raises(CloneFailedError):
        clones.clone_file(_source(tmp_path), tmp_path / "copy.bin")
    assert not os.path.lexists(tmp_path / "copy.bin")


def test_a_missing_source_fails_naming_both_paths_and_leaves_no_destination(
    tmp_path: Path,
) -> None:
    with pytest.raises(CloneFailedError) as caught:
        clones.clone_file(tmp_path / "missing", tmp_path / "copy.bin")
    assert caught.value.source == tmp_path / "missing"
    assert caught.value.destination == tmp_path / "copy.bin"
    assert not os.path.lexists(tmp_path / "copy.bin")
