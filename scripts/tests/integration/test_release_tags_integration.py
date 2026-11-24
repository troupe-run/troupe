"""Every version the manifest records has its release tag, and a missing one fails the release run,
naming the tag and the repair route (spec: releases; release-missing-components design D1, D2).

Its tests that stay in their own process are in unit/test_release_tags.py."""

import subprocess
import sys
from pathlib import Path

from conftest import SCRIPTS
from release_tags_shared import REPAIR, UNCONFIGURED, every_tag, read, released_0_2_0, write_root

from release_config import CONFIG, MANIFEST


def run(root: Path, refs: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPTS / "release_tags.py"), "--root", str(root)],
        input="".join(f"{ref}\n" for ref in refs),
        capture_output=True,
        text=True,
        check=False,
    )


def test_run_as_the_workflow_runs_it_exits_0_when_every_tag_exists(tmp_path: Path) -> None:
    root = write_root(tmp_path)
    result = run(root, every_tag(read(MANIFEST), read(CONFIG)))
    assert (result.returncode, result.stderr) == (0, "")


def test_run_as_the_workflow_runs_it_exits_1_naming_the_tags_and_the_repair(tmp_path: Path) -> None:
    manifest = released_0_2_0()
    root = write_root(tmp_path, manifest)
    gone = ("troupe-runner-ollama-v0.1.0", "protocol-v0.2.0")
    refs = [ref for ref in every_tag(manifest, read(CONFIG)) if not ref.endswith(gone)]
    result = run(root, refs)
    assert result.returncode == 1
    assert "troupe-runner-ollama-v0.1.0" in result.stderr
    assert "protocol-v0.2.0" in result.stderr
    assert REPAIR in result.stderr


def test_run_as_the_workflow_runs_it_exits_1_naming_an_unreadable_input(tmp_path: Path) -> None:
    root = write_root(tmp_path, read(MANIFEST) | {UNCONFIGURED: "0.1.0"})
    result = run(root, every_tag(read(MANIFEST), read(CONFIG)))
    assert result.returncode == 1
    assert UNCONFIGURED in result.stderr
