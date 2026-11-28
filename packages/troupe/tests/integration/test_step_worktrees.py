"""A flow's step works in a worktree built on the steps before it, and its end records its own
diff beside the performance's diff so far (spec: flows, "Each step works on the steps before it";
actor-sequences design D3, D4)."""

from pathlib import Path
from typing import Any

import pytest

from gitrepo import Repo
from runtesting import committed
from storetesting import git_service
from troupe.core.artifacts import load_store
from troupe.core.vcs import SharedChanges
from troupe.core.workspaces import (
    Worktree,
    build_on,
    capture,
    make_worktree,
    plan_worktree,
    worktree_base,
)


@pytest.fixture
def repo(tmp_path: Path) -> Repo:
    return committed(tmp_path)


def _ignore(_: object) -> None:
    pass


def _worktree(repo: Repo, run_id: str) -> Worktree:
    vcs = git_service(repo).vcs
    base, prefix = worktree_base(vcs, "tester")
    planned = plan_worktree(vcs, repo.path, run_id, base, prefix, _ignore)
    return make_worktree(vcs, planned, _ignore)


def _capture(repo: Repo, worktree: Worktree, artifacts: Any) -> dict[str, Any]:  # noqa: ANN401
    return capture(git_service(repo).vcs, worktree, artifacts, SharedChanges(), _ignore)


def test_a_step_built_on_the_first_records_its_own_diff_and_the_diff_so_far(
    repo: Repo, tmp_path: Path
) -> None:
    artifacts = load_store("local", tmp_path / "artifacts")
    first = _worktree(repo, "11111111-0000-4000-8000-000000000001")
    (first.path / "src" / "a.txt").write_text("from step one\n", encoding="utf-8")
    first_changes = _capture(repo, first, artifacts)
    assert "sofar" not in first_changes  # a first step's diff is the performance's

    second = _worktree(repo, "22222222-0000-4000-8000-000000000002")
    patch = tmp_path / "sofar.diff"
    patch.write_bytes(artifacts.read(first_changes["diff"]))
    second = build_on(git_service(repo).vcs, second, patch, _ignore)
    assert (second.path / "src" / "a.txt").read_text(encoding="utf-8") == "from step one\n"
    (second.path / "src" / "b.txt").write_text("from step two\n", encoding="utf-8")
    changes = _capture(repo, second, artifacts)

    own = artifacts.read(changes["diff"]).decode()
    assert "src/b.txt" in own
    assert "src/a.txt" not in own
    assert (changes["added"], changes["modified"], changes["deleted"]) == (0, 1, 0)
    sofar = artifacts.read(changes["sofar"]).decode()
    assert "src/a.txt" in sofar
    assert "src/b.txt" in sofar


def test_a_step_that_changes_nothing_still_records_the_work_so_far(
    repo: Repo, tmp_path: Path
) -> None:
    artifacts = load_store("local", tmp_path / "artifacts")
    first = _worktree(repo, "11111111-0000-4000-8000-000000000001")
    (first.path / "src" / "a.txt").write_text("from step one\n", encoding="utf-8")
    first_changes = _capture(repo, first, artifacts)
    second = _worktree(repo, "22222222-0000-4000-8000-000000000002")
    patch = tmp_path / "sofar.diff"
    patch.write_bytes(artifacts.read(first_changes["diff"]))
    second = build_on(git_service(repo).vcs, second, patch, _ignore)
    changes = _capture(repo, second, artifacts)
    assert "diff" not in changes
    assert "src/a.txt" in artifacts.read(changes["sofar"]).decode()


def test_the_workspace_a_later_step_records_names_the_run_it_was_built_on(
    repo: Repo,
) -> None:
    vcs = git_service(repo).vcs
    base, prefix = worktree_base(vcs, "tester")
    planned = plan_worktree(vcs, repo.path, "run", base, prefix, _ignore)
    earlier = "11111111-0000-4000-8000-000000000001"
    assert planned.record(repo.path, built_on=earlier)["builtOn"] == earlier
    assert "builtOn" not in planned.record(repo.path)
