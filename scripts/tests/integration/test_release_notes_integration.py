"""Every recorded version's release notes match its changelog section, apart from the heading's
date, and a release whose notes differ fails the release run, naming it (spec: releases;
release-notes-non-ascii design D1 to D7).

Its tests that stay in their own process are in unit/test_release_notes.py."""

import subprocess
import sys
from pathlib import Path

from conftest import SCRIPTS
from release_notes_shared import SECTION, WARNING, good, line, write_root


def run(root: Path, *args: str, stdin: str = "") -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [sys.executable, str(SCRIPTS / "release_notes.py"), "--root", str(root), *args],
        input=stdin.encode("utf-8"),
        capture_output=True,
        check=False,
    )


def test_the_script_exits_0_when_every_release_matches(tmp_path: Path) -> None:
    root = write_root(tmp_path)
    result = run(root, stdin="\n".join(good(root)) + "\n")
    assert (result.returncode, result.stderr) == (0, b"")


def test_the_script_exits_1_naming_a_release_that_differs(tmp_path: Path) -> None:
    root = write_root(tmp_path)
    lines = good(root)
    lines[0] = line("example-v0.2.0", SECTION.replace("⚠", "�"))
    result = run(root, stdin="\n".join(lines))
    assert result.returncode == 1
    stderr = result.stderr.decode("utf-8")
    assert "example-v0.2.0's notes differ" in stderr
    assert f"changelog: {WARNING}" in stderr


def test_the_script_exits_1_naming_an_unreadable_input(tmp_path: Path) -> None:
    result = run(write_root(tmp_path), stdin="not json\n")
    assert result.returncode == 1
    assert result.stderr.decode("utf-8").startswith("release notes: input line 1 isn't JSON")


def test_the_script_prints_a_tags_section_for_its_repair(tmp_path: Path) -> None:
    result = run(write_root(tmp_path), "--section", "example-v0.2.0")
    assert (result.returncode, result.stdout.decode("utf-8")) == (0, SECTION)


def test_the_script_refuses_the_section_of_an_unconfigured_tag(tmp_path: Path) -> None:
    result = run(write_root(tmp_path), "--section", "gone-v0.1.0")
    assert (result.returncode, result.stdout) == (1, b"")
    assert "'gone-v0.1.0'" in result.stderr.decode("utf-8")
