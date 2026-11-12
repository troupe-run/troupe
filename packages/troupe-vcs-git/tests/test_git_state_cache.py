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

import gitrepo
from gitrepo import AUTHOR, Repo, past_the_racy_window
from troupe.core.errors import TroupeError
from troupe.platform.processes import Completed
from troupe_vcs_git import GitAdapter


def make_repo(root: Path, name: str = "theatre", branch: str = "main", refs: str = "files") -> Repo:
    """Every repository in this file is built from scratch, never copied from a template: these
    tests are about the token's stats, the racy window and the reflogs a fresh init writes, which a
    copy could change (theatre-template-and-guard-xdist design D4)."""
    return gitrepo.make_repo(root, name, branch, refs, fresh=True)


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


def git_answer(repo: Repo, *args: str, stdin: bytes = b"") -> str | None:
    """What git prints for ``args`` when it answers, or None when it has no answer (exit 1)."""
    completed = subprocess.run(
        ["git", *args],  # noqa: S607 - git from the test environment's PATH
        cwd=repo.path,
        env={**repo.env, **AUTHOR},
        input=stdin,
        capture_output=True,
        check=False,
    )
    assert completed.returncode in (0, 1), completed.stderr
    return completed.stdout.decode("utf-8").strip() if completed.returncode == 0 else None


def gits_answers(repo: Repo) -> tuple[str | None, str | None]:
    """The branch and HEAD as git reports them now. The branch is git's short name as
    ``rev-parse --abbrev-ref=loose`` gives it, which is what lineage records once the branch has a
    commit (unborn-branch-short-name design D3). Not ``symbolic-ref --short``: it names a symbolic
    ref's target when one shares the branch's name (#388)."""
    head = git_answer(repo, "rev-parse", "--verify", "-q", "HEAD")
    full = git_answer(repo, "symbolic-ref", "--quiet", "HEAD")
    if full is None:
        return None, head  # detached
    if head is not None:
        return loose_short_name(repo), head
    return born_name(repo, full), None


def loose_short_name(repo: Repo) -> str:
    """``rev-parse --abbrev-ref=loose HEAD``, with ``--`` so a file named HEAD in the work tree
    can't make it ambiguous; rev-parse echoes the ``--`` on a line of its own."""
    answer = git_answer(repo, "rev-parse", "--abbrev-ref=loose", "HEAD", "--")
    assert answer is not None
    return answer.splitlines()[0]


def born_name(repo: Repo, full: str) -> str | None:
    """git's short name for the unborn branch ``full`` once it has a commit: an empty commit is
    given to it, the name read, and the branch's ref deleted again, which leaves HEAD unborn on
    the same branch with the same refs (design D3)."""
    tree = git_answer(repo, "mktree", stdin=b"")
    assert tree is not None
    commit = git_answer(repo, "commit-tree", "-m", "born for a moment", tree)
    assert commit is not None
    repo.git("update-ref", full, commit)
    try:
        return loose_short_name(repo)
    finally:
        repo.git("update-ref", "-d", full)


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
# what git's own rev-parse reports, for an unborn branch once it's born (gits_answers). Each check
# uses a fresh adapter, so it reads rather than answering from a cache.

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
        if ref == f"refs/heads/{current}" or self.symbolic(ref):
            return  # the branch itself; or a symbolic ref, which the rule below makes and drops
        exists = self.has(ref)
        if add and not exists:
            run_git(self.repo.path, self.repo, "update-ref", ref, "HEAD")
        elif not add and exists:
            run_git(self.repo.path, self.repo, "update-ref", "-d", ref)

    def symbolic(self, ref: str) -> bool:
        """Whether ``ref`` is a symbolic ref, its target there or not."""
        return git_answer(self.repo, "symbolic-ref", "--quiet", ref) is not None

    @rule(
        shape=st.sampled_from(["refs/tags/{}", "refs/{}"]),
        pointing_at=st.sampled_from(["missing", "existing"]),
        add=st.booleans(),
    )
    def a_symbolic_ref_named_after_the_branch(
        self, shape: str, pointing_at: str, add: bool
    ) -> None:
        """A symbolic ref with the current branch's name, to a missing ref or an existing branch,
        born or unborn (#388). git refuses one at the root, so only these two shapes."""
        current = self.current()
        if not current:
            return  # detached
        ref = shape.format(current)
        if ref.startswith("refs/heads/") or (self.has(ref) and not self.symbolic(ref)):
            return  # a branch; or a plain ref the rule above made and drops
        if not add:
            if self.symbolic(ref):
                run_git(self.repo.path, self.repo, "symbolic-ref", "--delete", ref)
            return
        if pointing_at == "missing":
            to = "refs/heads/gone"
        else:
            to = self.repo.git("for-each-ref", "--count=1", "--format=%(refname)", "refs/heads")
            to = to.strip()
            if not to:
                return  # no branch has a commit yet
        run_git(self.repo.path, self.repo, "symbolic-ref", ref, to)

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


def with_a_dangling_symbolic_ref_named_main(tmp_path: Path, refs: str) -> Repo:
    """A repository on ``main`` with ``refs/tags/main`` a symbolic ref to a missing branch."""
    repo = make_repo(tmp_path, refs=refs)
    empty_commit(repo)
    run_git(repo.path, repo, "symbolic-ref", "refs/tags/main", "refs/heads/gone")
    return repo


def test_under_the_files_storage_a_symbolic_ref_sharing_the_branchs_name_is_read_on_every_call(
    tmp_path: Path,
) -> None:
    # The short name depends on whether the symbolic ref's target exists, which nothing watched
    # shows (git-branch-cache design D3).
    git = adapter(with_a_dangling_symbolic_ref_named_main(tmp_path, "files"))
    git.branch_token()
    before = git.commands_run
    git.branch_token()
    git.branch_token()
    assert git.commands_run - before == 2


def test_under_reftable_a_symbolic_ref_sharing_the_branchs_name_is_reused_while_nothing_moves(
    tmp_path: Path,
) -> None:
    # The symbolic ref and its target are in the tables, whose watched lists change with either.
    git = adapter(with_a_dangling_symbolic_ref_named_main(tmp_path, "reftable"))
    git.branch_token()
    before = git.commands_run
    git.branch_token()
    git.branch_token()
    assert git.commands_run == before


@pytest.mark.parametrize("refs", ["files", "reftable"])
def test_the_cached_branch_follows_a_symbolic_ref_sharing_its_name_as_its_target_comes_and_goes(
    tmp_path: Path, refs: str
) -> None:
    # Compared with a fresh adapter, not symbolic-ref --short, which names the missing target
    # instead of the branch here (#388).
    repo = with_a_dangling_symbolic_ref_named_main(tmp_path, refs)
    git = adapter(repo)
    git.branch_token()
    steps: list[tuple[tuple[str, ...], str]] = [
        (("update-ref", "refs/heads/gone", "HEAD"), "heads/main"),
        (("update-ref", "-d", "refs/heads/gone"), "main"),
    ]
    for args, short in steps:
        settle()
        run_git(repo.path, repo, *args)
        fresh = GitAdapter(repo.path, source=repo.env)
        assert (git.branch(), git.head()) == (fresh.branch(), fresh.head())
        assert git.branch() == short


def reads_again(git: GitAdapter) -> int:
    """How many git commands two more reads of the branch and HEAD run, after a first."""
    git.branch_token()
    before = git.commands_run
    git.branch_token()
    git.branch_token()
    return git.commands_run - before


def test_head_naming_a_ref_outside_refs_heads_is_read_on_every_call_and_reports_gits_answers(
    tmp_path: Path,
) -> None:
    # git allows it, and its short name follows rules the token doesn't watch, so a read isn't
    # reused (git-branch-cache design D1).
    repo = make_repo(tmp_path)
    empty_commit(repo)
    make_ref(repo, "refs/tags/x")
    repo.git("symbolic-ref", "HEAD", "refs/tags/x")
    git = adapter(repo)
    assert reads_again(git) == 2
    assert (git.branch(), git.head()) == gits_answers(repo)


def test_a_ref_sharing_the_branchs_name_that_cant_be_read_is_read_on_every_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Whether it's a symbolic ref can't be told, so the read isn't trusted: refuse rather than
    # guess (git-branch-cache design D3). A permission error stands in for any read failure, as
    # file modes can't make one on every platform.
    repo = make_repo(tmp_path)
    empty_commit(repo)
    make_ref(repo, "refs/tags/main")
    unreadable = repo.path / ".git" / "refs" / "tags" / "main"
    real_open = Path.open

    def failing_open(self: Path, *args: object, **kwargs: object) -> object:
        if self == unreadable:
            raise PermissionError(13, "Permission denied", str(self))
        return real_open(self, *args, **kwargs)  # type: ignore[call-overload]

    monkeypatch.setattr(Path, "open", failing_open)
    git = adapter(repo)
    assert reads_again(git) == 2
    assert (git.branch(), git.head()) == gits_answers(repo)


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


# A symbolic ref sharing the branch's name (#388; unborn-branch-short-name). git's symbolic-ref
# --short shortens a name its own ambiguity check overwrites when that check follows a symbolic
# ref, so before the branch's first commit it named the target (gone, heads/main, one2). The
# adapter reports the name rev-parse --abbrev-ref=loose gives once the branch has a commit.


@dataclass(frozen=True)
class SymbolicName:
    """A symbolic ref ``ref`` to ``target``, made while ``main`` has a commit, and the short name
    git gives ``feature`` once it's born."""

    ref: str
    target: str
    short: str


SYMBOLIC_NAMES = {
    "tag-to-a-missing-branch": SymbolicName("refs/tags/feature", "refs/heads/gone", "feature"),
    "ref-to-a-missing-branch": SymbolicName("refs/feature", "refs/heads/gone", "feature"),
    "tag-to-an-existing-branch": SymbolicName(
        "refs/tags/feature", "refs/heads/main", "heads/feature"
    ),
    "tag-to-a-missing-tag": SymbolicName("refs/tags/feature", "refs/tags/gone2", "feature"),
}


@pytest.mark.parametrize("refs", ["files", "reftable"])
@pytest.mark.parametrize("case", SYMBOLIC_NAMES.values(), ids=SYMBOLIC_NAMES.keys())
def test_a_symbolic_ref_sharing_the_branchs_name_leaves_its_name_the_same_before_and_after_birth(
    tmp_path: Path, refs: str, case: SymbolicName
) -> None:
    repo = make_repo(tmp_path, refs=refs)
    empty_commit(repo)
    run_git(repo.path, repo, "symbolic-ref", case.ref, case.target)
    repo.git("switch", "-q", "--orphan", "feature")
    unborn = GitAdapter(repo.path, source=repo.env)
    assert (unborn.branch(), unborn.head()) == (case.short, None)
    empty_commit(repo)
    born = GitAdapter(repo.path, source=repo.env)
    assert born.branch() == case.short
    assert repo.git("rev-parse", "--abbrev-ref=loose", "HEAD").strip() == case.short


# What the unborn read relies on git for (unborn-branch-short-name design D2). git's documentation
# doesn't state these behaviours, so each is pinned here against the git this runs on: a change
# fails by name, before the differential tests.


def first_matches(repo: Repo, *names: str, warn: bool = False) -> tuple[int, list[str]]:
    """``rev-parse --symbolic-full-name --revs-only`` on ``names``, with ambiguity warnings on or
    off: its exit status and lines."""
    completed = subprocess.run(
        [  # noqa: S607 - git from the test environment's PATH
            "git",
            "-c",
            f"core.warnAmbiguousRefs={'true' if warn else 'false'}",
            "rev-parse",
            "--symbolic-full-name",
            "--revs-only",
            "--end-of-options",
            *names,
        ],
        cwd=repo.path,
        env=repo.env,
        capture_output=True,
        check=False,
    )
    return completed.returncode, completed.stdout.decode("utf-8").splitlines()


def git_version(repo: Repo) -> str:
    return repo.git("--version").strip()


@pytest.mark.parametrize("refs", ["files", "reftable"])
def test_git_names_a_symbolic_refs_target_not_the_ref_a_short_name_matched(
    tmp_path: Path, refs: str
) -> None:
    # Why the first match can't be read from --symbolic-full-name: it follows a symbolic ref.
    repo = make_repo(tmp_path, refs=refs)
    empty_commit(repo)
    run_git(repo.path, repo, "symbolic-ref", "refs/tags/pointer", "refs/heads/main")
    assert first_matches(repo, "pointer") == (0, ["refs/heads/main"]), git_version(repo)


@pytest.mark.parametrize("refs", ["files", "reftable"])
def test_git_lists_a_symbolic_ref_by_its_own_name_and_leaves_out_a_dangling_one(
    tmp_path: Path, refs: str
) -> None:
    repo = make_repo(tmp_path, refs=refs)
    empty_commit(repo)
    make_ref(repo, "refs/tags/plain")
    run_git(repo.path, repo, "symbolic-ref", "refs/tags/pointer", "refs/heads/main")
    run_git(repo.path, repo, "symbolic-ref", "refs/tags/dangling", "refs/heads/gone")
    make_ref(repo, "refs/tags/plain-and-more/below")
    listed = repo.git(
        "for-each-ref",
        "--format=%(refname)",
        "refs/tags/plain",
        "refs/tags/pointer",
        "refs/tags/dangling",
        "refs/tags/missing",
    ).splitlines()
    assert sorted(listed) == ["refs/tags/plain", "refs/tags/pointer"], git_version(repo)


@pytest.mark.parametrize("refs", ["files", "reftable"])
def test_git_counts_refs_a_name_matches_root_ones_included_with_ambiguity_warnings_on(
    tmp_path: Path, refs: str
) -> None:
    # How the unborn read tells whether a ref at the top of the git directory exists (design D2):
    # with warnings on, one match prints a name and two print nothing. A symbolic ref counts by
    # its own name, so it counts once, and a dangling one doesn't count.
    repo = make_repo(tmp_path, refs=refs)
    empty_commit(repo)
    version = git_version(repo)
    assert first_matches(repo, "ROOT", warn=True) == (0, []), version
    make_ref(repo, "ROOT")
    assert first_matches(repo, "ROOT", warn=True) == (0, ["ROOT"]), version
    make_ref(repo, "refs/remotes/ROOT")
    assert first_matches(repo, "ROOT", warn=True) == (0, []), version
    run_git(repo.path, repo, "symbolic-ref", "SYM", "refs/heads/main")
    assert first_matches(repo, "SYM", warn=True) == (0, ["refs/heads/main"]), version
    run_git(repo.path, repo, "symbolic-ref", "refs/tags/DANGLING", "refs/heads/gone")
    assert first_matches(repo, "DANGLING", warn=True) == (0, []), version


@dataclass(frozen=True)
class UnbornName:
    """Refs made while ``main`` has a commit, then an orphan ``branch``, and the short name git
    gives it once it's born."""

    refs: str
    branch: str
    made: tuple[str, ...]
    short: str


UNBORN_NAMES = {
    "upper-case-root-files": UnbornName("files", "ROOT", ("ROOT",), "heads/ROOT"),
    "upper-case-root-reftable": UnbornName("reftable", "ROOT", ("ROOT",), "heads/ROOT"),
    "upper-case-root-and-a-remote": UnbornName(
        "reftable", "ROOT", ("ROOT", "refs/remotes/ROOT"), "heads/ROOT"
    ),
    "only-a-remote": UnbornName("files", "origin", ("refs/remotes/origin",), "origin"),
    "lower-case-root-files": UnbornName("files", "low", ("low",), "heads/low"),
    "heads-at-the-root-behind-a-tag": UnbornName(
        "files", "x", ("refs/tags/x", "heads/x"), "refs/heads/x"
    ),
    "nothing-shares-the-name": UnbornName("reftable", "plain", (), "plain"),
}


@pytest.mark.parametrize("case", UNBORN_NAMES.values(), ids=UNBORN_NAMES.keys())
def test_an_unborn_branch_has_the_short_name_git_gives_it_once_born(
    tmp_path: Path, case: UnbornName
) -> None:
    repo = make_repo(tmp_path, refs=case.refs)
    empty_commit(repo)
    for ref in case.made:
        make_ref(repo, ref)
    repo.git("switch", "-q", "--orphan", case.branch)
    unborn = GitAdapter(repo.path, source=repo.env)
    assert (unborn.branch(), unborn.head()) == (case.short, None)
    assert gits_answers(repo) == (case.short, None)


def test_an_unborn_branch_name_gits_answers_cant_settle_is_refused(tmp_path: Path) -> None:
    # heads/x at the top of the git directory, with two refs under refs/ sharing heads/x: git
    # prints nothing for two matches or three, so whether heads/x exists can't be told (D2).
    repo = make_repo(tmp_path, refs="files")
    empty_commit(repo)
    for ref in ("refs/tags/x", "heads/x", "refs/tags/heads/x", "refs/remotes/heads/x"):
        make_ref(repo, ref)
    repo.git("switch", "-q", "--orphan", "x")
    with pytest.raises(TroupeError) as caught:
        GitAdapter(repo.path, source=repo.env).branch()
    assert caught.value.code == "vcs.short-name-undecided"
    assert caught.value.details == {
        "branch": "refs/heads/x",
        "name": "heads/x",
        "refs": ["refs/tags/heads/x", "refs/remotes/heads/x"],
    }


def test_a_root_candidate_after_one_that_isnt_a_ref_is_neither_needed_nor_refused(
    tmp_path: Path,
) -> None:
    # Claude's review on #399: .git/config is a file named after a branch "config" but not a ref,
    # so git resolves "config" to nothing and reads heads/config after it as a path. The walk
    # stops at "config", so heads/config's missing answer must not refuse the read.
    repo = make_repo(tmp_path, refs="files")
    empty_commit(repo)
    make_ref(repo, "heads/config")
    repo.git("switch", "-q", "--orphan", "config")
    unborn = GitAdapter(repo.path, source=repo.env)
    assert (unborn.branch(), unborn.head()) == ("config", None)
    assert gits_answers(repo) == ("config", None)
