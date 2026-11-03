"""perform audits every run's changes against its actor's declared effects, in a worktree and in
the theatre (spec: effects, "Every run's changes are audited against its declaration", "The audit
sees changes as git sees them" and "A failed audit fails the run and names every change"; spec:
actor-runners, "Success needs an ok result, a passing effect check and a clean exit";
declared-effects design D3, D4)."""

from pathlib import Path
from typing import Any

import pytest

from runtesting import INIT, OK, Harness, request, script, theatre
from troupe_plugin_sdk.messages import Message


def _write(path: str, content: str = "x\n") -> dict[str, Any]:
    return {"writeFile": {"path": path, "content": content}}


def _ended(harness: Harness, asked: dict[str, Any]) -> dict[str, Any]:
    result = harness.perform_result(asked)
    assert result.run is not None
    data: dict[str, Any] = result.run.to_data()
    return data


@pytest.mark.parametrize("workspace", ["worktree", "theatre"])
def test_a_write_outside_the_declaration_fails_the_run_naming_the_path(
    tmp_path: Path, workspace: str
) -> None:
    harness = Harness(theatre(tmp_path))
    asked = request(
        script(INIT, _write("out/a.txt"), _write("src/a.py"), OK),
        effects={"write": ["out/**"]},
        workspace=workspace,
    )
    if workspace == "worktree":
        harness.repo.commit_all("a commit for the worktree to start from")
    run = _ended(harness, asked)
    assert run["outcome"] == "failed"
    assert run["error"]["code"] == "effects.outside-declared"
    assert run["error"]["details"]["changes"] == [
        {"path": "src/a.py", "change": "added", "needs": "write"}
    ]
    assert "src/a.py" in run["error"]["fix"]


def test_a_write_inside_the_declaration_succeeds(tmp_path: Path) -> None:
    harness = Harness(theatre(tmp_path))
    run = _ended(
        harness,
        request(script(INIT, _write("out/a.txt"), OK), effects={"write": ["out/**"]}),
    )
    assert run["outcome"] == "succeeded", run.get("error")


def test_expecting_nothing_still_audits_and_the_run_fails(tmp_path: Path) -> None:
    harness = Harness(theatre(tmp_path))
    run = _ended(harness, request(script(INIT, _write("out/a.txt"), OK)))
    assert run["outcome"] == "failed"
    assert run["error"]["code"] == "effects.outside-declared"


def test_an_ignored_build_output_passes_the_audit(tmp_path: Path) -> None:
    harness = Harness(theatre(tmp_path))
    (harness.repo.path / ".gitignore").write_bytes(b"__pycache__/\n")
    harness.repo.commit_all("ignore")
    run = _ended(harness, request(script(INIT, _write("__pycache__/a.pyc"), OK)))
    assert run["outcome"] == "succeeded", run.get("error")


def test_a_change_made_before_a_theatre_run_and_left_alone_passes(tmp_path: Path) -> None:
    harness = Harness(theatre(tmp_path))
    (harness.repo.path / "src").mkdir()
    (harness.repo.path / "src" / "a.py").write_bytes(b"one\n")
    harness.repo.commit_all("a")
    (harness.repo.path / "src" / "a.py").write_bytes(b"uncommitted\n")
    run = _ended(harness, request(script(INIT, OK)))
    assert run["outcome"] == "succeeded", run.get("error")


def test_expected_and_undeclared_failures_are_both_named(tmp_path: Path) -> None:
    harness = Harness(theatre(tmp_path))
    asked = request(
        script(INIT, _write("src/a.py"), OK),
        effect={"kind": "files", "paths": ["out/hello.txt"]},
    )
    run = _ended(harness, asked)
    assert run["outcome"] == "failed"
    assert run["error"]["code"] == "effects.check-failed"
    codes = [inner["code"] for inner in run["error"]["details"]["errors"]]
    assert codes == ["run.effect-missing", "effects.outside-declared"]


class _EditsDuringTheRun(Harness):
    """A person who edits notes.md in the theatre as soon as the run's first event arrives."""

    edited: bool = False

    def send(self, update: Message) -> None:
        super().send(update)
        if not self.edited and update.to_data().get("kind") == "event":
            (self.repo.path / "notes.md").write_bytes(b"edited by a person\n")
            self.edited = True


def test_someone_editing_the_theatre_during_a_run_fails_its_audit_saying_why(
    tmp_path: Path,
) -> None:
    harness = _EditsDuringTheRun(theatre(tmp_path))
    run = _ended(harness, request(script(INIT, {"wait": {"ms": 200}}, OK)))
    assert harness.edited
    assert run["outcome"] == "failed"
    assert run["error"]["details"]["changes"] == [
        {"path": "notes.md", "change": "added", "needs": "write"}
    ]
    assert "counts every change made there while it ran, by anyone" in run["error"]["problem"]
