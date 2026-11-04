"""perform records the audit of every run whose runner started, whatever its outcome, without
changing a failed run's outcome or error (spec: effects, "Every run's changes are audited against
its declaration", "A failed run's audit doesn't change its outcome" and "An audit that can't read
the workspace says so"; spec: runs, "A run's end records its audit"; failed-run-audit design D1-D3).
"""

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from runtesting import INIT, OK, Harness, request, script, theatre
from troupe.core.errors import TroupeError
from troupe.core.runners.limits import RunLimits
from troupe_plugin_sdk.messages import Message
from troupe_vcs_git import GitAdapter

ERROR = {"event": {"type": "result", "status": "error", "message": "it went wrong"}}


def _write(path: str, content: str = "x\n") -> dict[str, Any]:
    return {"writeFile": {"path": path, "content": content}}


def _run(harness: Harness, asked: dict[str, Any]) -> dict[str, Any]:
    result = harness.perform_result(asked)
    assert result.run is not None
    data: dict[str, Any] = result.run.to_data()
    return data


def test_a_failed_worktree_run_keeps_its_error_and_records_the_change_outside(
    tmp_path: Path,
) -> None:
    harness = Harness(theatre(tmp_path))
    harness.repo.commit_all("a commit for the worktree to start from")
    asked = request(
        script(INIT, _write("src/a.py"), ERROR),
        effects={"write": ["out/**"]},
        workspace="worktree",
    )
    run = _run(harness, asked)
    assert run["outcome"] == "failed"
    assert run["error"]["code"] == "run.error-result"
    assert run["audit"] == {"outside": [{"path": "src/a.py", "change": "added", "needs": "write"}]}
    assert run["changes"]["state"] == "pending", "its changes are kept, to accept or discard"


def test_a_timed_out_run_keeps_its_error_and_records_the_change_outside(tmp_path: Path) -> None:
    harness = Harness(
        theatre(tmp_path), limits=RunLimits(start_timeout=10.0, cancel_grace=2.0, run_timeout=1.0)
    )
    run = _run(harness, request(script(INIT, _write("notes.md"), {"hang": True})))
    assert run["outcome"] == "timed-out"
    assert run["error"]["code"] == "run.timeout"
    assert run["audit"] == {"outside": [{"path": "notes.md", "change": "added", "needs": "write"}]}


class _RemovesThenCancels(Harness):
    """A person who removes README.md from the theatre once the run's first event arrives, then
    cancels the run."""

    done: bool = False

    def send(self, update: Message) -> None:
        super().send(update)
        if not self.done and update.to_data().get("kind") == "event":
            (self.repo.path / "README.md").unlink()
            self.cancel.request()
            self.done = True


def test_a_cancelled_run_keeps_no_error_and_records_the_removal_outside(tmp_path: Path) -> None:
    harness = _RemovesThenCancels(theatre(tmp_path))
    (harness.repo.path / "README.md").write_bytes(b"read me\n")
    harness.repo.commit_all("a readme")
    run = _run(harness, request(script(INIT, {"hang": True}), effects={"write": ["**"]}))
    assert harness.done
    assert run["outcome"] == "cancelled"
    assert "error" not in run
    assert run["audit"] == {
        "outside": [{"path": "README.md", "change": "removed", "needs": "delete"}]
    }


def test_a_failed_run_that_stayed_inside_its_declaration_records_an_empty_audit(
    tmp_path: Path,
) -> None:
    harness = Harness(theatre(tmp_path))
    run = _run(
        harness, request(script(INIT, _write("out/a.txt"), ERROR), effects={"write": ["out/**"]})
    )
    assert run["error"]["code"] == "run.error-result"
    assert run["audit"] == {"outside": []}


def test_a_failed_run_isnt_checked_for_its_expected_file(tmp_path: Path) -> None:
    harness = Harness(theatre(tmp_path))
    asked = request(script(INIT, ERROR), effect={"kind": "files", "paths": ["out/hello.txt"]})
    run = _run(harness, asked)
    assert run["error"]["code"] == "run.error-result"
    assert "hello.txt" not in run["error"]["problem"]


def test_a_run_that_succeeds_records_an_empty_audit(tmp_path: Path) -> None:
    harness = Harness(theatre(tmp_path))
    run = _run(
        harness, request(script(INIT, _write("out/a.txt"), OK), effects={"write": ["out/**"]})
    )
    assert run["outcome"] == "succeeded", run.get("error")
    assert run["audit"] == {"outside": []}


def _unreadable_after_the_start(monkeypatch: pytest.MonkeyPatch) -> None:
    """git reads the workspace for the audit's start, then fails for its end."""
    real = GitAdapter.file_states
    calls = {"n": 0}

    def file_states(self: GitAdapter, directory: Path, at: str | None = None) -> Mapping[str, str]:
        calls["n"] += 1
        if calls["n"] > 1:
            raise TroupeError(
                "vcs.failed",
                problem="git ls-files failed.",
                fix="Check the repository with git status.",
                details={"command": "git ls-files", "exitStatus": 128},
            )
        return real(self, directory, at)

    monkeypatch.setattr(GitAdapter, "file_states", file_states)


def test_an_ok_run_whose_workspace_cant_be_read_fails_and_its_end_is_still_recorded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = Harness(theatre(tmp_path))
    _unreadable_after_the_start(monkeypatch)
    run = _run(harness, request(script(INIT, OK)))
    assert run["state"] == "ended"
    assert run["outcome"] == "failed"
    assert run["error"]["code"] == "effects.audit-failed"
    assert run["audit"]["error"]["code"] == "vcs.failed"


def test_a_cancelled_run_whose_workspace_cant_be_read_stays_cancelled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = _RemovesThenCancels(theatre(tmp_path))
    (harness.repo.path / "README.md").write_bytes(b"read me\n")
    harness.repo.commit_all("a readme")
    _unreadable_after_the_start(monkeypatch)
    run = _run(harness, request(script(INIT, {"hang": True})))
    assert run["outcome"] == "cancelled"
    assert "error" not in run
    assert run["audit"]["error"]["code"] == "vcs.failed"
