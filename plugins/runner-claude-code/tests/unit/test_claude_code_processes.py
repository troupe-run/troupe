"""Finding, starting and stopping Claude Code's process, on every platform (design D6, D7, D9).

Its tests that start a process, open a socket or use a git theatre are in
integration/test_claude_code_processes_integration.py."""

import os
import stat
import sys
from pathlib import Path

import pytest

from troupe_runner_claude_code import processes


def test_find_claude_finds_the_program_on_an_absolute_path_entry(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    name = "claude.cmd" if sys.platform == "win32" else "claude"
    program = bin_dir / name
    program.write_text("@echo off\r\n" if sys.platform == "win32" else "#!/bin/sh\n")
    program.chmod(program.stat().st_mode | stat.S_IXUSR)
    found = processes.find_claude(os.pathsep.join([str(tmp_path / "empty"), str(bin_dir)]))
    assert found is not None
    assert found.parent == bin_dir
    assert found.name.lower() == name


def test_find_claude_skips_relative_and_empty_path_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "claude").write_text("#!/bin/sh\n")
    (tmp_path / "claude").chmod(0o755)
    (tmp_path / "claude.cmd").write_text("@echo off\r\n")
    monkeypatch.chdir(tmp_path)
    assert processes.find_claude(os.pathsep.join(["", ".", "relative"])) is None


def test_find_claude_finds_nothing_without_a_path() -> None:
    assert processes.find_claude(None) is None
    assert processes.find_claude("") is None


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX needs the executable bit")
def test_find_claude_skips_a_file_that_isnt_executable_on_posix(tmp_path: Path) -> None:
    (tmp_path / "claude").write_text("#!/bin/sh\n")
    (tmp_path / "claude").chmod(0o644)
    assert processes.find_claude(str(tmp_path)) is None


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (0, 0),
        (1, 1),
        (143, 143),
        (255, 255),
        (-15, 143),
        (-9, 137),
        (0x74726B6C, 1),
        (-1073741510, 1),
    ],
)
def test_exit_code_maps_claude_codes_status_onto_the_runners_exit_code(
    status: int, code: int
) -> None:
    assert processes.exit_code(status) == code
