"""The git adapter's branch token and its cached branch and HEAD (spec: vcs; cache-vcs-state design
D1-D4, D7).

Every test runs against real repositories, across both ref storages (files and reftable) and with
reflogs on and off, because which of git's files a move touches depends on both.
"""

import os
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import pytest
from hypothesis import HealthCheck, settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, rule

from gitrepo import AUTHOR, Repo, isolated_environment, past_the_racy_window
from troupe_vcs_git import GitAdapter

REFTABLE_NEEDS = "reftable needs git >= 2.45 (git init --ref-format=reftable)"


@cache
def reftable_supported() -> bool:
    with tempfile.TemporaryDirectory() as scratch:
        completed = subprocess.run(
            ["git", "init", "-q", "--ref-format=reftable", scratch],  # noqa: S607
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
    if layout.refs == "reftable" and not reftable_supported():
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


# The differential test (design D7 test 2): after any sequence of moves, the cached adapter answers
# exactly as an adapter that caches nothing, which is what the adapter did before the cache.


class Moves(RuleBasedStateMachine):
    """Random moves of the branch and HEAD, checked against a fresh adapter after each one."""

    layout = LAYOUTS[0]
    now: Callable[[], int] = staticmethod(time.time_ns)

    def __init__(self) -> None:
        super().__init__()
        self.root = Path(tempfile.mkdtemp())
        self.repo = make_layout_repo(self.root, self.layout)
        self.branches = ["main", "other", "feature"]
        self.linked = self.root / "linked"
        self.repo.git("worktree", "add", "-q", "--detach", str(self.linked))
        self.cached = GitAdapter(self.repo.path, source=self.repo.env, now=type(self).now)
        self.renames = 0

    def teardown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    @rule()
    def commit(self) -> None:
        commit(self.repo)

    @rule()
    def empty_commit(self) -> None:
        empty_commit(self.repo)

    @rule(pick=st.integers(min_value=0))
    def switch(self, pick: int) -> None:
        self.repo.git("switch", "-q", "--discard-changes", self.branches[pick % len(self.branches)])

    @rule()
    def detach(self) -> None:
        detach(self.repo)

    @rule(mode=st.sampled_from(["--soft", "--mixed", "--hard"]), pick=st.integers(min_value=0))
    def reset(self, mode: str, pick: int) -> None:
        self.repo.git("reset", "-q", mode, self.branches[pick % len(self.branches)])

    @rule(pick=st.integers(min_value=0))
    def merge(self, pick: int) -> None:
        target = self.branches[pick % len(self.branches)]
        self.repo.git("merge", "-q", "--no-ff", "--no-edit", "-X", "theirs", target)

    @rule(pick=st.integers(min_value=0), to=st.integers(min_value=0))
    def update_ref_from_a_linked_worktree(self, pick: int, to: int) -> None:
        branch = self.branches[pick % len(self.branches)]
        target = self.branches[to % len(self.branches)]
        run_git(self.linked, self.repo, "update-ref", f"refs/heads/{branch}", target)

    @rule()
    def pack_refs(self) -> None:
        self.repo.git("pack-refs", "--all")

    @rule()
    def rename_the_current_branch(self) -> None:
        current = self.repo.git("branch", "--show-current").strip()
        if not current:
            return  # detached: nothing to rename
        self.renames += 1
        renamed = f"renamed-{self.renames}"
        self.repo.git("branch", "-m", renamed)
        self.branches[self.branches.index(current)] = renamed

    @invariant()
    def the_cached_answers_are_gits(self) -> None:
        now = fresh(self.repo)
        assert (self.cached.branch(), self.cached.head()) == (now.branch(), now.head())


def _moves(layout: Layout, now: Callable[[], int]) -> type[Moves]:
    machine: type[Moves] = type(
        f"Moves_{layout.id}", (Moves,), {"layout": layout, "now": staticmethod(now)}
    )
    machine.TestCase.settings = settings(
        max_examples=4,
        stateful_step_count=10,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    return machine


# Past the racy window, the stats alone must catch every move; with the real clock and the default
# windows, this is the configuration troupe ships.
TestMovesFilesReflogsOnStatsOnly = _moves(LAYOUTS[0], past_the_racy_window).TestCase
TestMovesFilesReflogsOffStatsOnly = _moves(LAYOUTS[1], past_the_racy_window).TestCase
TestMovesReftableReflogsOnStatsOnly = _moves(LAYOUTS[2], past_the_racy_window).TestCase
TestMovesReftableReflogsOffStatsOnly = _moves(LAYOUTS[3], past_the_racy_window).TestCase
TestMovesFilesReflogsOnAsShipped = _moves(LAYOUTS[0], time.time_ns).TestCase
TestMovesFilesReflogsOffAsShipped = _moves(LAYOUTS[1], time.time_ns).TestCase
TestMovesReftableReflogsOnAsShipped = _moves(LAYOUTS[2], time.time_ns).TestCase
TestMovesReftableReflogsOffAsShipped = _moves(LAYOUTS[3], time.time_ns).TestCase
