"""troupe's git adapter for the VCS port (spec: vcs; event-store design D1, D4, D11).

Every git command runs through troupe.core.commands with GIT_ENVIRONMENT, so git sees its own
config, credentials and SSH agent, but never a hook's GIT_DIR or GIT_INDEX_FILE, and nothing else of
troupe's environment. Only local commands run (symbolic-ref, rev-parse, ls-files, ls-tree, config,
and for a run's worktree: worktree, status, read-tree, checkout-index, update-index, diff-files,
add, write-tree, diff, apply, for-each-ref; for merge sides: cat-file, merge-tree; for marking a
merged path resolved: hash-object, update-index), so git never
starts a credential helper or ssh. The worktree operations live in troupe_vcs_git.worktrees, and
merge sides in troupe_vcs_git.merges.

The branch and HEAD are cached behind the branch token: the stats of every file git changes when
either moves, and of every ref git weighs in shortening the branch's name, such as a tag with that
name. They are read through git again only when one of those files has changed, so recording event
after event runs no command while nothing moves (cache-vcs-state design D1, D3; git-branch-cache
design D1, D2). A read again is one rev-parse once HEAD has a commit (git-call-latency design D4).

A directory is in a repository only when git reports it inside a work tree, so neither a git
directory nor a bare repository can hold a theatre (init-and-audition design D7).
"""

import os
import shlex
import time
from collections.abc import Callable, Hashable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from troupe.core.commands import run_command
from troupe.core.errors import TroupeError
from troupe.core.vcs import (
    Applicability,
    Captured,
    Clone,
    Filled,
    Marked,
    MergeSides,
    Resolve,
    SharedState,
    not_a_repository,
)
from troupe.platform.processes import Completed, EnvironmentPolicy, ProcessWaitCallback
from troupe_vcs_git import defaults
from troupe_vcs_git.merges import Merges
from troupe_vcs_git.states import States
from troupe_vcs_git.worktrees import Worktrees

# Exit status 1 means "no answer" for these, not failure: an unborn or detached HEAD, a missing key.
_NO_ANSWER = 1
_NOT_A_REPOSITORY = 128
"""git's exit status when no repository holds the directory, among other fatal errors."""
_NOT_A_REPOSITORY_MESSAGE = b"not a git repository"
"""What git's message says when that is the reason, as opposed to, say, a dubious owner."""
_INIT_FIX = (
    "Make it a git repository first with git init (or run troupe init inside one), then run "
    "troupe init again. troupe never makes a repository for you."
)

# The files git changes when the branch or HEAD moves (cache-vcs-state design D3), as --git-path
# names them. Per worktree: HEAD, the index, HEAD's reflog and, under reftable, the table list that
# holds HEAD. Common: packed-refs. The common reftable list and the branch's own loose ref are found
# through --git-common-dir, and the refs sharing the branch's name below.
_WATCHED = ("HEAD", "index", "logs/HEAD", "packed-refs", "reftable/tables.list")

_BRANCHES = "refs/heads/"

# Where git looks for a ref sharing the branch's name when it shortens refs/heads/<n> (#370;
# git-branch-cache design D1). Any of these existing makes <n> ambiguous, and then heads/<n> at the
# root decides between heads/<n> and refs/heads/<n>. Which directory git reads each from depends on
# the name, so every one is watched in both the worktree's git directory and the common one.
_SHORT_NAME_REFS = ("{}", "heads/{}", "refs/{}", "refs/tags/{}")

# Under reftable every other ref is in the tables, whose lists are watched. git still keeps its
# special refs as files in the worktree's git directory, and reads them for a branch of that name
# (git-branch-cache design D2).
_SPECIAL_REFS = ("FETCH_HEAD", "MERGE_HEAD")

_Stat = tuple[int, int, int] | None

_SECOND = 1_000_000_000


@dataclass(frozen=True)
class _State:
    """The branch and HEAD, and the stats of the files that were watched when they were read."""

    watched: tuple[_Stat, ...]
    ref: Path | None
    ref_stat: _Stat
    sharing: tuple[Path, ...]
    """The refs that would share the branch's name, which git weighs in shortening it."""
    sharing_stats: tuple[_Stat, ...]
    branch: str | None
    head: str | None
    racy: bool
    """Whether a watched file changed within the racy window of the read, or the read can't be
    trusted for another reason: if so, it isn't reused."""

    @property
    def token(self) -> Hashable:
        return (self.watched, self.ref_stat, self.sharing_stats, self.branch, self.head)


class GitAdapter:
    """The VCS port, read through git in the theatre's directory."""

    def __init__(
        self,
        theatre: Path,
        *,
        policy: EnvironmentPolicy = defaults.GIT_ENVIRONMENT,
        timeout: float = defaults.GIT_TIMEOUT_SECONDS,
        announce_after: float = defaults.GIT_ANNOUNCE_AFTER_SECONDS,
        max_output_bytes: int = defaults.GIT_MAX_OUTPUT_BYTES,
        source: Mapping[str, str] | None = None,
        on_wait: ProcessWaitCallback | None = None,
        racy_window: float = defaults.GIT_RACY_WINDOW_SECONDS,
        coarse_racy_window: float = defaults.GIT_COARSE_RACY_WINDOW_SECONDS,
        now: Callable[[], int] = time.time_ns,
        worktree_timeout: float = defaults.GIT_WORKTREE_TIMEOUT_SECONDS,
        worktree_max_output_bytes: int = defaults.GIT_WORKTREE_MAX_OUTPUT_BYTES,
        diff_max_bytes: int = defaults.GIT_DIFF_MAX_BYTES,
    ) -> None:
        self.theatre = theatre
        self.policy = policy
        self.timeout = timeout
        self.announce_after = announce_after
        self.max_output_bytes = max_output_bytes
        self.source = source
        self.on_wait = on_wait
        self.racy_window = racy_window
        self.coarse_racy_window = coarse_racy_window
        self.now = now
        """The wall clock, in nanoseconds, that file timestamps are compared with (design D4)."""
        self.worktree_timeout = worktree_timeout
        self.worktree_max_output_bytes = worktree_max_output_bytes
        self.diff_max_bytes = diff_max_bytes
        self.commands_run = 0
        """How many git commands this adapter has run, so callers can check their cost."""
        self._watched: tuple[Path, ...] | None = None
        self._common: Path | None = None
        self._state: _State | None = None
        self._worktrees = Worktrees(self)
        self._states = States(self)
        self._merges = Merges(self)

    @property
    def name(self) -> str:
        return "git"

    def check_repository(self) -> None:
        completed = self.git("rev-parse", "--is-inside-work-tree", allow=(0, _NOT_A_REPOSITORY))
        if completed.returncode == _NOT_A_REPOSITORY:
            if _NOT_A_REPOSITORY_MESSAGE not in completed.stderr:
                # Another fatal error, such as a repository git refuses to read: say what git said.
                raise self.failed(["git", "rev-parse", "--is-inside-work-tree"], completed)
        elif completed.stdout.strip() == b"true":
            return
        raise not_a_repository("git", self.theatre.absolute(), _INIT_FIX)

    def git(self, *args: str, allow: Sequence[int] = (0,)) -> Completed:
        """Run ``git args`` in the theatre; any exit status outside ``allow`` is vcs.failed."""
        return self.git_in(
            self.theatre,
            *args,
            allow=allow,
            timeout=self.timeout,
            max_output_bytes=self.max_output_bytes,
        )

    def git_in(
        self,
        cwd: Path,
        *args: str,
        allow: Sequence[int] = (0,),
        timeout: float,
        max_output_bytes: int,
        input: bytes | None = None,
    ) -> Completed:
        """Run ``git args`` in ``cwd`` within the limits given; any exit status outside ``allow``
        is vcs.failed."""
        argv = ["git", *args]
        self.commands_run += 1
        completed = run_command(
            argv,
            cwd=cwd,
            policy=self.policy,
            timeout=timeout,
            max_output_bytes=max_output_bytes,
            announce_after=self.announce_after,
            source=self.source,
            on_wait=self.on_wait,
            input=input,
        )
        if completed.returncode not in allow:
            raise self.failed(argv, completed, cwd)
        return completed

    def failed(
        self, argv: Sequence[str], completed: Completed, cwd: Path | None = None
    ) -> TroupeError:
        """vcs.failed for ``argv``, which ended as ``completed``."""
        message = completed.stderr.decode("utf-8", "replace").strip() or "no message"
        return TroupeError(
            "vcs.failed",
            problem=f"{shlex.join(argv)} failed with exit status {completed.returncode}: {message}",
            fix="Check that the theatre is a git repository and that git works there, then try "
            "again.",
            path=str((cwd or self.theatre).absolute()),
            details={"command": shlex.join(argv), "exitStatus": completed.returncode},
        )

    def branch(self) -> str | None:
        return self._current().branch

    def head(self) -> str | None:
        return self._current().head

    def branch_token(self) -> Hashable:
        # The stats of every file git changes when the branch or HEAD moves, with the branch and
        # HEAD read when they were taken: it changes exactly when they might have (design D1, D3).
        return self._current().token

    def _current(self) -> _State:
        """The branch and HEAD, read through git only when a watched file has changed since the
        last read (cache-vcs-state design D1)."""
        common, paths = self._paths()
        read_at = self.now()
        watched = tuple(_stat_token(path) for path in paths)
        state = self._state
        if (
            state is not None
            and not state.racy
            and state.watched == watched
            and (state.ref is None or _stat_token(state.ref) == state.ref_stat)
            and tuple(_stat_token(path) for path in state.sharing) == state.sharing_stats
        ):
            return state
        # Stat before reading: a move during the read leaves the stats older than the answers, so
        # the next call reads again. It never leaves the answers older than the stats. The branch's
        # ref is named by the HEAD file, as git reads it, and stat'd before the command too
        # (git-call-latency design D4), with the refs that would share its name (git-branch-cache
        # design D1, D2).
        reftable = watched[-1] is not None
        named = _ref_named_by(paths[0], common)
        named_stat = None if named is None else _stat_token(named)
        sharing, unknown_name = _sharing(named, common, paths[0].parent, reftable=reftable)
        sharing_stats = tuple(_stat_token(path) for path in sharing)
        if _looks_unborn(watched, named, named_stat):
            branch, head, ref = self._read_unborn(common)
        else:
            branch, head, ref = self._read(common)
        moved = ref != named and not reftable  # HEAD moved between its file and the command
        ref_stat = named_stat if ref == named else None if ref is None else _stat_token(ref)
        racy = (
            moved
            or unknown_name
            or _any_symbolic(sharing, sharing_stats)
            or self._racy(read_at, (*watched, ref_stat, *sharing_stats))
        )
        state = _State(watched, ref, ref_stat, sharing, sharing_stats, branch, head, racy)
        self._state = state
        return state

    def _read(self, common: Path) -> tuple[str | None, str | None, Path | None]:
        """The branch, HEAD and the branch's ref file, read in one command once HEAD has a commit
        (git-call-latency design D4). ``--abbrev-ref=loose`` gives the short name exactly as
        ``symbolic-ref --short`` does, as lineage has always recorded it (cache-vcs-state D2);
        both say ``HEAD`` when it is detached."""
        completed = self.git(
            "rev-parse",
            "HEAD",
            "--symbolic-full-name",
            "HEAD",
            "--abbrev-ref=loose",
            "HEAD",
            "--",
            allow=(0, _NOT_A_REPOSITORY),
        )
        if completed.returncode == 0:
            head, full, short, _ = completed.stdout.decode("utf-8").splitlines()
            if full == "HEAD":
                return None, head, None  # detached
            return short, head, common / full
        # No commit yet, or a failure: the commands that tell those apart without reading git's
        # message, where exit status 1 means no answer and anything else is vcs.failed.
        return self._read_unborn(common)

    def _read_unborn(self, common: Path) -> tuple[str | None, str | None, Path | None]:
        full = self.git("symbolic-ref", "--quiet", "HEAD", allow=(0, _NO_ANSWER))
        ref: Path | None = None
        branch: str | None = None
        if full.returncode != _NO_ANSWER:  # detached, otherwise
            ref = common / full.stdout.decode("utf-8").strip()
            short = self.git("symbolic-ref", "--quiet", "--short", "HEAD", allow=(0, _NO_ANSWER))
            if short.returncode != _NO_ANSWER:
                branch = short.stdout.decode("utf-8").strip()
        return branch, self._read_head(), ref

    def _racy(self, read_at: int, stats: tuple[_Stat, ...]) -> bool:
        """Git's own "racily clean" rule: an answer read within the window of a watched file's last
        change could miss a second change in the same timestamp tick, so it's used once (D4). The
        window is longer when every mtime is a whole second: coarse timestamps."""
        mtimes = [stat[0] for stat in stats if stat is not None]
        coarse = all(mtime % _SECOND == 0 for mtime in mtimes)
        window = self.coarse_racy_window if coarse else self.racy_window
        recent = read_at - int(window * _SECOND)
        return any(mtime >= recent for mtime in mtimes)

    def _read_head(self) -> str | None:
        completed = self.git("rev-parse", "--verify", "--quiet", "HEAD", allow=(0, _NO_ANSWER))
        if completed.returncode == _NO_ANSWER:
            return None  # no commit yet
        return completed.stdout.decode("ascii").strip()

    def _paths(self) -> tuple[Path, tuple[Path, ...]]:
        """The common git directory and the watched files, found with one command per adapter."""
        if self._common is None or self._watched is None:
            args = [arg for name in _WATCHED for arg in ("--git-path", name)]
            out = self.git("rev-parse", "--git-common-dir", *args).stdout.decode("utf-8")
            common, *paths = out.splitlines()
            self._common = self.theatre / common
            self._watched = (
                *(self.theatre / path for path in paths),
                self._common / "reftable" / "tables.list",
            )
        return self._common, self._watched

    def committed_under(self, directory: str) -> frozenset[str]:
        staged = self.git("ls-files", "-z", "--", directory)
        names = set(_nul_separated(staged.stdout))
        if self.head() is not None:
            in_head = self.git("ls-tree", "-r", "-z", "--name-only", "HEAD", "--", directory)
            names.update(_nul_separated(in_head.stdout))
        return frozenset(names)

    def merge_sides_under(self, directory: str) -> Mapping[str, MergeSides]:
        return self._merges.under(directory)

    def mark_resolved(self, paths: Mapping[str, Resolve]) -> Marked:
        return self._merges.mark(paths)

    def configured_identities(self) -> tuple[str, ...]:
        completed = self.git(
            "config", "--get-all", "--show-scope", "-z", "user.email", allow=(0, _NO_ANSWER)
        )
        if completed.returncode == _NO_ANSWER:
            return ()
        fields = completed.stdout.decode("utf-8").split("\0")
        if fields and fields[-1] == "":
            fields.pop()  # the terminator after the last value; an empty value is kept as a field
        by_scope: dict[str, list[str]] = {}
        for scope, value in zip(fields[::2], fields[1::2], strict=True):
            by_scope.setdefault(scope, []).append(value)
        # git reads scopes from least to most specific, and a more specific scope overrides a less
        # specific one, so the last scope listed wins. Several values within that one scope are an
        # ambiguity git would settle silently (the last one); troupe refuses instead.
        winning = list(by_scope.values())[-1]
        values = [value for value in winning if value.strip()]
        return tuple(dict.fromkeys(values))

    # The worktree operations (worktree-stage design D4), in troupe_vcs_git.worktrees.

    def theatre_prefix(self) -> str:
        return self._worktrees.theatre_prefix()

    def differing_from_head(self) -> tuple[str, ...]:
        return self._worktrees.differing_from_head()

    def add_worktree(self, path: Path, at: str) -> None:
        self._worktrees.add_worktree(path, at)

    def fill_worktree(self, path: Path, clone: Clone, skip: frozenset[str]) -> Filled:
        return self._worktrees.fill_worktree(path, clone, skip)

    def capture(self, path: Path, baseline: str, leave_out: tuple[str, ...], out: Path) -> Captured:
        return self._worktrees.capture(path, baseline, leave_out, out)

    def check_apply(self, diff: Path) -> Applicability:
        return self._worktrees.check_apply(diff)

    def apply(self, diff: Path) -> tuple[str, ...]:
        return self._worktrees.apply(diff)

    def remove_worktree(self, path: Path) -> None:
        self._worktrees.remove_worktree(path)

    def shared_state(self) -> SharedState:
        return self._worktrees.shared_state()

    def file_states(self, directory: Path, at: str | None = None) -> Mapping[str, str]:
        return self._states.file_states(directory, at)


def _ref_named_by(head_file: Path, common: Path) -> Path | None:
    """The ref file the HEAD file names, as git reads it: ``ref: <full name>`` on a branch. None
    when HEAD is detached, or the file can't be read (git will say why)."""
    try:
        text = head_file.read_text("utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    if not text.startswith("ref: "):
        return None
    return common / text.removeprefix("ref: ").strip()


def _sharing(
    named: Path | None, common: Path, git_dir: Path, *, reftable: bool
) -> tuple[tuple[Path, ...], bool]:
    """The files git may read to decide the branch's short name, besides the branch's own ref, and
    whether the name is one these can't cover (git-branch-cache design D1, D2)."""
    if reftable:
        return tuple(git_dir / name for name in _SPECIAL_REFS), False
    if named is None:
        return (), False  # detached, or a HEAD file git will say is broken: no short name
    full = named.relative_to(common).as_posix()
    if not full.startswith(_BRANCHES):
        return (), True  # HEAD names a ref outside refs/heads/, whose shortening isn't watched
    name = full.removeprefix(_BRANCHES)
    directories = dict.fromkeys((git_dir, common))  # one, in the main worktree
    paths = tuple(
        directory / shape.format(name) for shape in _SHORT_NAME_REFS for directory in directories
    )
    return paths, False


def _any_symbolic(paths: tuple[Path, ...], stats: tuple[_Stat, ...]) -> bool:
    """Whether any of ``paths`` that existed when stat'd holds a symbolic ref. git's short name then
    depends on whether its target exists, which nothing watched shows, so the read isn't reused
    (git-branch-cache design D3). One that can't be read counts as symbolic: refuse rather than
    guess."""
    for path, stat in zip(paths, stats, strict=True):
        if stat is None or path.is_dir():
            continue  # a directory of refs (refs/tags/<n>/...) isn't a ref named <n>
        try:
            with path.open("rb") as file:
                if file.read(5) == b"ref: ":
                    return True
        except OSError:
            return True
    return False


def _looks_unborn(watched: tuple[_Stat, ...], named: Path | None, named_stat: _Stat) -> bool:
    """Whether HEAD looks unborn, from files alone: a files-backend repository with no
    ``packed-refs``, whose HEAD names a loose ref that doesn't exist. Only which commands read the
    answers depends on this, never the answers: an unborn HEAD is read in three commands rather
    than a failed rev-parse and those three (git-call-latency design D5)."""
    packed_refs, common_tables = watched[_WATCHED.index("packed-refs")], watched[-1]
    if packed_refs is not None or common_tables is not None:
        return False  # refs may be packed, or kept in reftable: only git can tell
    return named is not None and named_stat is None


def _nul_separated(data: bytes) -> list[str]:
    return [item for item in data.decode("utf-8").split("\0") if item]


def _stat_token(path: Path) -> _Stat:
    try:
        info = os.stat(path)
    except (FileNotFoundError, NotADirectoryError):
        return None  # under reftable, refs/heads is a file, so a path below it is not a directory
    return (info.st_mtime_ns, info.st_size, info.st_ino)
