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
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

import pytest
from hypothesis import HealthCheck, settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, rule

from gitrepo import AUTHOR, Repo, make_repo, past_the_racy_window
from troupe.platform.processes import Completed
from troupe_vcs_git import GitAdapter


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
    repo = make_repo(root, refs=layout.refs)
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


def gits_answers(repo: Repo) -> tuple[str | None, str | None]:
    """The branch and HEAD as git reports them now, by the two commands the adapter ran before it
    cached anything."""
    answers: list[str | None] = []
    for args in (
        ["symbolic-ref", "--quiet", "--short", "HEAD"],
        ["rev-parse", "--verify", "-q", "HEAD"],
    ):
        completed = subprocess.run(
            ["git", *args],  # noqa: S607 - git from the test environment's PATH
            cwd=repo.path,
            env=repo.env,
            capture_output=True,
            check=False,
        )
        assert completed.returncode in (0, 1), completed.stderr
        answers.append(
            completed.stdout.decode("utf-8").strip() if completed.returncode == 0 else None
        )
    return answers[0], answers[1]


def run_git(cwd: Path, repo: Repo, *args: str) -> None:
    subprocess.run(
        ["git", *args],  # noqa: S607 - git from the test environment's PATH
        cwd=cwd,
        env={**repo.env, **AUTHOR},
        check=True,
        capture_output=True,
    )


def make_ref(repo: Repo, ref: str) -> None:
    run_git(repo.path, repo, "update-ref", ref, "HEAD")


def drop_ref(repo: Repo, ref: str) -> None:
    """Delete ``ref``. git makes a root ref with a lower-case name but refuses to delete it ("bad
    name"), so one outside refs/ is deleted as its file, from whichever git directory holds it."""
    if ref.startswith("refs/"):
        run_git(repo.path, repo, "update-ref", "-d", ref)
        return
    for directory in repo.git("rev-parse", "--git-dir", "--git-common-dir").splitlines():
        (repo.path / directory / ref).unlink(missing_ok=True)


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
    assert (git.branch(), git.head()) == gits_answers(repo)


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

    def drop_leftovers(self) -> None:
        """A soft or mixed reset leaves changes, and can leave a merged file untracked, which git
        won't switch or merge over. Dropping them moves no ref."""
        self.repo.git("reset", "-q", "--hard")
        self.repo.git("clean", "-q", "-f", "-d")

    @rule(pick=st.integers(min_value=0))
    def switch(self, pick: int) -> None:
        self.drop_leftovers()
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
        self.drop_leftovers()
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

    @rule(shape=st.sampled_from(("refs/tags/{}", "refs/{}", "{}")), add=st.booleans())
    def a_ref_named_after_the_branch(self, shape: str, add: bool) -> None:
        """A tag, a ref directly under refs/ or a root ref with the current branch's name: each
        changes git's short name for it (#370)."""
        current = self.repo.git("branch", "--show-current").strip()
        if not current or (shape == "{}" and self.layout.refs == "reftable"):
            return  # detached; or a root ref reftable can't delete again (see SHORT_NAME_SHAPES)
        ref = shape.format(current)
        exists = (self.repo.path / ".git" / ref).is_file() or bool(
            self.repo.git("for-each-ref", "--format=%(refname)", ref).strip()
        )
        if add and not exists:
            make_ref(self.repo, ref)
        elif not add and exists:
            drop_ref(self.repo, ref)

    @invariant()
    def the_cached_answers_are_gits(self) -> None:
        assert (self.cached.branch(), self.cached.head()) == gits_answers(self.repo)


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


# Past the racy window, the stats alone must catch every move, in every layout. Once more with the
# real clock and the default windows, the configuration troupe ships, in the layout git's files
# reveal least about (reftable, no reflogs).
TestMovesFilesReflogsOnStatsOnly = _moves(LAYOUTS[0], past_the_racy_window).TestCase
TestMovesFilesReflogsOffStatsOnly = _moves(LAYOUTS[1], past_the_racy_window).TestCase
TestMovesReftableReflogsOnStatsOnly = _moves(LAYOUTS[2], past_the_racy_window).TestCase
TestMovesReftableReflogsOffStatsOnly = _moves(LAYOUTS[3], past_the_racy_window).TestCase
TestMovesReftableReflogsOffAsShipped = _moves(LAYOUTS[3], time.time_ns).TestCase


# The racy window (design D4). The clock is set relative to the newest file in the git directory,
# which every watched file is in.

SECOND = 1_000_000_000


def newest_git_file(repo: Repo) -> int:
    return max(
        os.stat(Path(directory) / name).st_mtime_ns
        for directory, _, names in os.walk(repo.path / ".git")
        for name in names
    )


def reads_twice(repo: Repo, now: int) -> int:
    """How many git commands a second read of the branch and HEAD runs, the clock at ``now``."""
    git = GitAdapter(repo.path, source=repo.env, now=lambda: now)
    git.branch_token()
    before = git.commands_run
    git.branch_token()
    cost = git.commands_run - before
    assert (git.branch(), git.head()) == gits_answers(repo)
    return cost


def test_a_read_within_the_racy_window_is_read_again(repo: Repo) -> None:
    assert reads_twice(repo, newest_git_file(repo) + SECOND // 20) == 1


def test_a_read_past_the_racy_window_is_reused(repo: Repo) -> None:
    assert reads_twice(repo, newest_git_file(repo) + SECOND) == 0


def test_whole_second_timestamps_get_the_coarse_window(repo: Repo) -> None:
    whole = (newest_git_file(repo) // SECOND + 1) * SECOND
    for directory, _, names in os.walk(repo.path / ".git"):
        for name in names:
            os.utime(Path(directory) / name, ns=(whole, whole))
    # Past the 0.1 s window, but within the 2 s one that coarse timestamps get.
    assert reads_twice(repo, whole + SECOND) == 1
    assert reads_twice(repo, whole + 3 * SECOND) == 0


# The read itself (git-call-latency design D4): whatever refs share the checked-out branch's name,
# whether HEAD is born, unborn or detached, and whatever the work tree holds, a read reports exactly
# what git's own symbolic-ref --short and rev-parse report. Each check uses a fresh adapter, so it
# reads rather than answering from a cache.

NAME_REFS = (
    "refs/tags/{}",
    "refs/{}",
    "refs/remotes/{}",
    "refs/remotes/{}/HEAD",
    "refs/heads/heads/{}",
)
"""Refs whose existence changes, or could change, git's short name for ``refs/heads/<name>``."""


class Names(RuleBasedStateMachine):
    """Random names, births and detaches, with each read checked against git's own answers."""

    layout = LAYOUTS[0]

    def __init__(self) -> None:
        super().__init__()
        self.root = Path(tempfile.mkdtemp())
        self.repo = make_repo(self.root, refs=self.layout.refs)
        self.orphans = 0

    def teardown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def current(self) -> str:
        return self.repo.git("branch", "--show-current").strip()

    def has(self, ref: str) -> bool:
        found = subprocess.run(
            ["git", "show-ref", "--verify", "-q", ref],  # noqa: S607 - git from PATH
            cwd=self.repo.path,
            env=self.repo.env,
            check=False,
        )
        return found.returncode == 0

    def born(self) -> bool:
        head = subprocess.run(
            ["git", "rev-parse", "--verify", "-q", "HEAD"],  # noqa: S607 - git from PATH
            cwd=self.repo.path,
            env=self.repo.env,
            capture_output=True,
            check=False,
        )
        return head.returncode == 0

    @rule()
    def commit(self) -> None:
        empty_commit(self.repo)

    @rule(name=st.sampled_from(["main", "heads/main", "tags/main", "heads/x", "tags/x", "x"]))
    def switch_to_a_new_branch(self, name: str) -> None:
        if not self.born() or self.has(f"refs/heads/{name}"):
            return
        self.repo.git("switch", "-q", "-c", name)

    @rule()
    def start_an_orphan_branch(self) -> None:
        self.orphans += 1
        self.repo.git("switch", "-q", "--orphan", f"orphan-{self.orphans}")

    @rule()
    def detach(self) -> None:
        if self.born():
            self.repo.git("switch", "-q", "--detach")

    @rule(shape=st.sampled_from(NAME_REFS), add=st.booleans())
    def a_ref_named_after_the_branch(self, shape: str, add: bool) -> None:
        current = self.current()
        if not current or not self.born():
            return
        ref = shape.format(current)
        if ref == f"refs/heads/{current}":
            return
        exists = self.has(ref)
        if add and not exists:
            run_git(self.repo.path, self.repo, "update-ref", ref, "HEAD")
        elif not add and exists:
            run_git(self.repo.path, self.repo, "update-ref", "-d", ref)

    @rule(kind=st.sampled_from(["file", "directory", "none"]))
    def something_named_head_in_the_work_tree(self, kind: str) -> None:
        target = self.repo.path / "HEAD"
        if target.is_dir():
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()
        if kind == "file":
            target.write_text("not a ref\n")
        elif kind == "directory":
            target.mkdir()
            (target / "inside").write_text("not a ref\n")

    @invariant()
    def a_read_reports_gits_answers(self) -> None:
        fresh = GitAdapter(self.repo.path, source=self.repo.env)
        assert (fresh.branch(), fresh.head()) == gits_answers(self.repo)


def _names(layout: Layout) -> type[Names]:
    machine: type[Names] = type(f"Names_{layout.id}", (Names,), {"layout": layout})
    # As small as the Moves machines: each step is several git commands, which on a slow Windows
    # runner took this machine to ~40 s at 10 x 12 (#380). The per-shape test below pins each
    # name that changes the short name; the machine is for their combinations.
    machine.TestCase.settings = settings(
        max_examples=4,
        stateful_step_count=10,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    return machine


TestNamesFiles = _names(LAYOUTS[0]).TestCase
TestNamesReftable = _names(LAYOUTS[2]).TestCase


@pytest.mark.parametrize("refs", ["files", "reftable"])
@pytest.mark.parametrize("shape", NAME_REFS)
def test_a_ref_sharing_the_branchs_name_leaves_gits_short_name(
    tmp_path: Path, refs: str, shape: str
) -> None:
    repo = make_repo(tmp_path, refs=refs)
    empty_commit(repo)
    run_git(repo.path, repo, "update-ref", shape.format("main"), "HEAD")
    fresh = GitAdapter(repo.path, source=repo.env)
    assert (fresh.branch(), fresh.head()) == gits_answers(repo)


# A cached adapter follows git's short name as refs sharing the branch's name come and go (#370;
# git-branch-cache design D1). The clock is past the racy window, so only the token can notice.

SHORT_NAME_SHAPES = ("refs/tags/{}", "refs/{}", "{}")
"""Refs whose existence makes git shorten ``refs/heads/<name>`` to ``heads/<name>``: a tag, a ref
directly under ``refs/``, and a root ref (git-branch-cache design, the probe table)."""


def create_then_delete(short: str, unchanged: str) -> list[tuple[Callable[[Repo, str], None], str]]:
    """Making then deleting a ref, each with git's short name for the branch after it."""
    return [(make_ref, short), (drop_ref, unchanged)]


@pytest.mark.parametrize(
    ("refs", "shape"),
    [
        (refs, shape)
        for refs in ("files", "reftable")
        for shape in SHORT_NAME_SHAPES
        # Under reftable, git 2.56 makes a lower-case root ref in the tables but refuses to
        # delete it ("bad name"), and there's no file to delete instead (see drop_ref).
        if not (refs == "reftable" and shape == "{}")
    ],
)
def test_a_ref_sharing_the_branchs_name_changes_the_cached_short_name(
    tmp_path: Path, refs: str, shape: str
) -> None:
    repo = make_repo(tmp_path, refs=refs)
    empty_commit(repo)
    git = adapter(repo)
    assert git.branch() == "main"
    ref = shape.format("main")
    for operation, short in create_then_delete("heads/main", "main"):
        before = git.branch_token()
        settle()
        operation(repo, ref)
        assert gits_answers(repo)[0] == short, "the operation didn't change git's short name"
        assert git.branch_token() != before
        assert (git.branch(), git.head()) == gits_answers(repo)


@dataclass(frozen=True)
class SharedName:
    """A ref sharing the branch's name, made in a theatre that's a linked worktree or the main
    one, and git's short name for the branch once it exists."""

    refs: str
    linked: bool
    branch: str
    ref: str
    short: str
    before: tuple[str, ...] = ()
    """A ref made first, with the adapter's clock past the racy window too."""


# Where git reads each from (git-branch-cache design, the probe table): a lower-case root ref and
# refs/<n> from the common directory; an upper-case root ref and refs/bisect/... from the
# worktree's own.
SHARED_NAMES = {
    "linked-worktree-tag": SharedName("files", True, "wt", "refs/tags/wt", "heads/wt"),
    "linked-worktree-lower-case-root": SharedName("files", True, "wt", "wt", "heads/wt"),
    "linked-worktree-upper-case-root": SharedName("files", True, "WT", "WT", "heads/WT"),
    "linked-worktree-bisect": SharedName(
        "files", True, "bisect/x", "refs/bisect/x", "heads/bisect/x"
    ),
    "heads-at-the-root-behind-a-tag": SharedName(
        "files", False, "main", "heads/main", "refs/heads/main", before=("refs/tags/main",)
    ),
    "reftable-linked-worktree-tag": SharedName("reftable", True, "wt", "refs/tags/wt", "heads/wt"),
}


def theatre_for(tmp_path: Path, case: SharedName) -> Repo:
    """The main worktree on ``main``, or a linked worktree on a new branch, as the theatre."""
    repo = make_repo(tmp_path, refs=case.refs)
    empty_commit(repo)
    if not case.linked:
        return repo
    linked = tmp_path / "linked"
    repo.git("worktree", "add", "-q", "-b", case.branch, str(linked))
    return Repo(linked, repo.env)


@pytest.mark.parametrize("case", SHARED_NAMES.values(), ids=SHARED_NAMES.keys())
def test_a_ref_sharing_the_branchs_name_where_git_reads_it_changes_the_cached_short_name(
    tmp_path: Path, case: SharedName
) -> None:
    theatre = theatre_for(tmp_path, case)
    for ref in case.before:
        make_ref(theatre, ref)
    git = adapter(theatre)
    unchanged = git.branch()
    assert unchanged is not None
    assert unchanged != case.short
    for operation, short in create_then_delete(case.short, unchanged):
        settle()
        operation(theatre, case.ref)
        assert gits_answers(theatre)[0] == short, "the operation didn't change git's short name"
        assert (git.branch(), git.head()) == gits_answers(theatre)


def test_under_reftable_a_fetch_onto_a_branch_named_fetch_head_changes_the_cached_short_name(
    tmp_path: Path,
) -> None:
    # git keeps FETCH_HEAD as a file even under reftable, and refuses to delete it with update-ref,
    # so only its arrival is checked (git-branch-cache design D2).
    repo = make_repo(tmp_path, refs="reftable")
    empty_commit(repo)
    repo.git("switch", "-q", "-c", "FETCH_HEAD")
    git = adapter(repo)
    assert git.branch() == "FETCH_HEAD"
    settle()
    run_git(repo.path, repo, "fetch", "-q", ".", "HEAD")
    assert gits_answers(repo)[0] == "heads/FETCH_HEAD", "the fetch didn't change git's short name"
    assert (git.branch(), git.head()) == gits_answers(repo)


@pytest.mark.parametrize("refs", ["files", "reftable"])
def test_a_symbolic_ref_sharing_the_branchs_name_is_read_on_every_call_and_followed(
    tmp_path: Path, refs: str
) -> None:
    # The short name depends on whether the symbolic ref's target exists, which nothing watched
    # shows (git-branch-cache design D3). Compared with a fresh adapter, not symbolic-ref --short,
    # which names the missing target instead of the branch here (#388).
    repo = make_repo(tmp_path, refs=refs)
    empty_commit(repo)
    run_git(repo.path, repo, "symbolic-ref", "refs/tags/main", "refs/heads/gone")
    git = adapter(repo)
    git.branch_token()
    before = git.commands_run
    git.branch_token()
    git.branch_token()
    # Under reftable the symbolic ref and its target are in the tables, whose lists are watched.
    assert git.commands_run - before == (2 if refs == "files" else 0)
    for args in (
        ("update-ref", "refs/heads/gone", "HEAD"),
        ("update-ref", "-d", "refs/heads/gone"),
    ):
        settle()
        run_git(repo.path, repo, *args)
        fresh = GitAdapter(repo.path, source=repo.env)
        assert (git.branch(), git.head()) == (fresh.branch(), fresh.head())


# Stat, then read (git-call-latency design D4): the branch's ref is stat'd before the one command
# that names it, so a move landing between that command and any later stat is still seen. The clock
# is past the racy window, so only the stat can catch it; reflogs are off and refs are files, so the
# move changes the ref's own file and nothing else.


class MovesDuringTheRead(GitAdapter):
    """An adapter that, once, moves ``branch`` to ``to`` just after the command that reads HEAD."""

    def __init__(self, repo: Repo, branch: str, to: str) -> None:
        super().__init__(repo.path, source=repo.env, now=past_the_racy_window)
        self.repo = repo
        self.move: tuple[str, str] | None = (branch, to)

    def git(self, *args: str, allow: Sequence[int] = (0,)) -> Completed:
        completed = super().git(*args, allow=allow)
        if self.move is not None and args[:2] == ("rev-parse", "HEAD"):
            branch, to = self.move
            self.move = None
            settle()
            run_git(self.repo.path, self.repo, "update-ref", f"refs/heads/{branch}", to)
        return completed


@pytest.mark.parametrize("when", ["a new adapter's first read", "the read after a switch"])
def test_a_move_between_reading_head_and_statting_the_ref_is_seen(
    tmp_path: Path, when: str
) -> None:
    repo = make_layout_repo(tmp_path, Layout("files", reflogs=False))
    feature = repo.git("rev-parse", "feature").strip()
    if when == "a new adapter's first read":
        git = MovesDuringTheRead(repo, "main", feature)
    else:
        git = MovesDuringTheRead(repo, "other", feature)
        move, git.move = git.move, None
        git.branch_token()
        settle()
        repo.git("switch", "-q", "other")
        git.move = move
    git.branch_token()  # the read, during which the branch moves
    assert git.move is None, "the read ran no command for the move to follow"
    assert (git.branch(), git.head()) == gits_answers(repo)
