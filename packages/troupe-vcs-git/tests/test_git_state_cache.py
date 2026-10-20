"""The git adapter's branch token and its cached branch and HEAD (spec: vcs; cache-vcs-state design
D1-D4, D7).

Every test runs against real repositories, across both ref storages (files and reftable) and with
reflogs on and off, because which of git's files a move touches depends on both.
"""

import os
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import pytest

from gitrepo import AUTHOR, Repo, isolated_environment, past_the_racy_window
from troupe_vcs_git import GitAdapter

REFTABLE_NEEDS = "reftable needs git >= 2.45 (git init --ref-format=reftable)"


@cache
def reftable_supported(scratch: Path) -> bool:
    completed = subprocess.run(
        ["git", "init", "-q", "--ref-format=reftable", str(scratch / "probe")],  # noqa: S607
        capture_output=True,
        check=False,
    )
    return completed.returncode == 0


@dataclass(frozen=True)
class Layout:
    """How a test repository stores its refs, and whether it keeps reflogs."""

    refs: str
    reflogs: bool

    @property
    def id(self) -> str:
        return f"{self.refs}-reflogs-{'on' if self.reflogs else 'off'}"


LAYOUTS = [Layout(refs, reflogs) for refs in ("files", "reftable") for reflogs in (True, False)]


def make_layout_repo(root: Path, layout: Layout) -> Repo:
    """A repository with two commits on ``main``, a branch ``other`` at the same commit (same
    tree), and a branch ``feature`` one commit ahead with a different tree."""
    if layout.refs == "reftable" and not reftable_supported(root):
        if os.environ.get("CI"):
            pytest.fail(f"{REFTABLE_NEEDS}; CI must run the reftable cases, not skip them")
        pytest.skip(REFTABLE_NEEDS)
    path = root / "theatre"
    path.mkdir(parents=True)
    repo = Repo(path, isolated_environment(root / "theatre-home"))
    repo.git("init", "-q", "-b", "main", f"--ref-format={layout.refs}")
    repo.git("config", "core.logAllRefUpdates", "true" if layout.reflogs else "false")
    repo.write("a.txt", "a")
    repo.commit_all("one")
    repo.write("b.txt", "b")
    repo.commit_all("two")
    repo.git("branch", "other")
    repo.git("switch", "-q", "-c", "feature")
    repo.write("f.txt", "f")
    repo.commit_all("feature")
    repo.git("switch", "-q", "main")
    return repo


@pytest.fixture(params=LAYOUTS, ids=lambda layout: layout.id)
def layout(request: pytest.FixtureRequest) -> Layout:
    value: Layout = request.param
    return value


@pytest.fixture
def repo(tmp_path: Path, layout: Layout) -> Repo:
    return make_layout_repo(tmp_path, layout)


def adapter(repo: Repo) -> GitAdapter:
    """An adapter whose clock is past the racy window, so what it notices, it notices through the
    token's stats alone (design D4)."""
    return GitAdapter(repo.path, source=repo.env, now=past_the_racy_window)


def fresh(repo: Repo) -> GitAdapter:
    """An adapter that has cached nothing: what git reports now."""
    return GitAdapter(repo.path, source=repo.env)


def run_git(cwd: Path, repo: Repo, *args: str) -> None:
    subprocess.run(
        ["git", *args],  # noqa: S607 - git from the test environment's PATH
        cwd=cwd,
        env={**repo.env, **AUTHOR},
        check=True,
        capture_output=True,
    )


# The operations, each a move of the branch or HEAD made by another process (git).


def commit(repo: Repo) -> None:
    repo.write(f"c{time.monotonic_ns()}.txt", "c")
    repo.commit_all("commit")


def empty_commit(repo: Repo) -> None:
    repo.git("commit", "-q", "--allow-empty", "-m", "empty")


def switch_same_tree(repo: Repo) -> None:
    repo.git("switch", "-q", "other")


def detach(repo: Repo) -> None:
    repo.git("switch", "-q", "--detach")


def commit_while_detached(repo: Repo) -> None:
    repo.git("switch", "-q", "--detach")
    empty_commit(repo)


def reset_soft(repo: Repo) -> None:
    repo.git("reset", "-q", "--soft", "HEAD~")


def reset_mixed(repo: Repo) -> None:
    repo.git("reset", "-q", "--mixed", "HEAD~")


def reset_hard(repo: Repo) -> None:
    repo.git("reset", "-q", "--hard", "HEAD~")


def merge(repo: Repo) -> None:
    repo.git("merge", "-q", "--no-ff", "--no-edit", "feature")


def update_ref_from_a_linked_worktree(repo: Repo) -> None:
    linked = repo.path.parent / f"linked-{time.monotonic_ns()}"
    repo.git("worktree", "add", "-q", "--detach", str(linked))
    run_git(linked, repo, "update-ref", "refs/heads/main", "HEAD~")


def pack_refs_then_commit(repo: Repo) -> None:
    repo.git("pack-refs", "--all")
    empty_commit(repo)


OPERATIONS: dict[str, Callable[[Repo], None]] = {
    "commit": commit,
    "empty-commit": empty_commit,
    "switch-same-tree": switch_same_tree,
    "detach": detach,
    "commit-while-detached": commit_while_detached,
    "reset-soft": reset_soft,
    "reset-mixed": reset_mixed,
    "reset-hard": reset_hard,
    "merge": merge,
    "update-ref-from-a-linked-worktree": update_ref_from_a_linked_worktree,
    "pack-refs-then-commit": pack_refs_then_commit,
}


def settle() -> None:
    """Let the clock pass a timestamp tick, so a rewritten file can't keep its old mtime."""
    time.sleep(0.02)


@pytest.mark.parametrize("operation", OPERATIONS)
def test_every_move_of_the_branch_or_head_changes_the_token_and_the_answers_follow(
    repo: Repo, operation: str
) -> None:
    git = adapter(repo)
    before = git.branch_token()
    settle()
    OPERATIONS[operation](repo)
    assert git.branch_token() != before
    now = fresh(repo)
    assert (git.branch(), git.head()) == (now.branch(), now.head())
