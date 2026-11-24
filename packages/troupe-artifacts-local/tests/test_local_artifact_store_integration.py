"""Tests for the local artifact store (spec: artifact-store), as a store behind the port.

Its tests that stay in their own process are in unit/test_local_artifact_store.py."""

import subprocess
from pathlib import Path

from troupe_artifacts_local import LocalArtifactStore

# Requirement: The local store stays out of version control


def test_artifacts_in_a_store_inside_a_git_working_tree_do_not_show_in_git_status(
    tmp_path: Path,
) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)  # noqa: S607
    (tmp_path / "tracked.txt").write_text("user file\n", encoding="utf-8")
    store = LocalArtifactStore(tmp_path / ".troupe" / "local" / "artifacts")
    store.put(b"transcript")
    with store.open_writer() as writer:
        writer.write(b"half")  # a writer in progress leaves a temporary file too
        status = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all"],  # noqa: S607
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    assert status.splitlines() == ["?? tracked.txt"]
    assert (tmp_path / "tracked.txt").read_text(encoding="utf-8") == "user file\n"
