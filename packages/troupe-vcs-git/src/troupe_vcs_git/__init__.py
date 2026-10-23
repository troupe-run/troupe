"""troupe's git adapter for the VCS port (spec: vcs; event-store design D1, D4, D11).

Every git command runs through troupe.core.commands with GIT_ENVIRONMENT, so git sees its own
config, credentials and SSH agent, but never a hook's GIT_DIR or GIT_INDEX_FILE, and nothing else of
troupe's environment. Only local commands run (symbolic-ref, rev-parse, ls-files, ls-tree, config,
and for a run's worktree: worktree, status, read-tree, checkout-index, update-index, diff-files,
add, write-tree, diff, apply, for-each-ref), so git never starts a credential helper or ssh. The
worktree operations live in troupe_vcs_git.worktrees.

The branch and HEAD are cached behind the branch token: the stats of every file git changes when
either moves. They are read through git again only when one of those files has changed, so
recording event after event runs no command while nothing moves (cache-vcs-state design D1, D3).
"""

import os
import shlex
import time
from collections.abc import Callable, Hashable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from troupe.core.commands import run_command
from troupe.core.errors import TroupeError
from troupe.core.vcs import Applicability, Captured, Clone, Filled, SharedState
from troupe.platform.processes import Completed, EnvironmentPolicy, ProcessWaitCallback
from troupe_vcs_git import defaults
from troupe_vcs_git.worktrees import Worktrees

# Exit status 1 means "no answer" for these, not failure: an unborn or detached HEAD, a missing key.
_NO_ANSWER = 1

# The files git changes when the branch or HEAD moves (cache-vcs-state design D3), as --git-path
# names them. Per worktree: HEAD, the index, HEAD's reflog and, under reftable, the table list that
# holds HEAD. Common: packed-refs. The common reftable list and the branch's own loose ref are found
# through --git-common-dir.
_WATCHED = ("HEAD", "index", "logs/HEAD", "packed-refs", "reftable/tables.list")

_Stat = tuple[int, int, int] | None

_SECOND = 1_000_000_000


@dataclass(frozen=True)
class _State:
    """The branch and HEAD, and the stats of the files that were watched when they were read."""

    watched: tuple[_Stat, ...]
    ref: Path | None
    ref_stat: _Stat
    branch: str | None
    head: str | None
    racy: bool
    """Whether a watched file changed within the racy window of the read: if so, it isn't reused."""

    @property
    def token(self) -> Hashable:
        return (self.watched, self.ref_stat, self.branch, self.head)


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

    @property
    def name(self) -> str:
        return "git"

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
        ):
            return state
        # Stat before reading: a move during the read leaves the stats older than the answers, so
        # the next call reads again. It never leaves the answers older than the stats.
        full = self.git("symbolic-ref", "--quiet", "HEAD", allow=(0, _NO_ANSWER))
        ref: Path | None = None
        ref_stat: _Stat = None
        branch: str | None = None
        if full.returncode != _NO_ANSWER:  # detached, otherwise
            ref = common / full.stdout.decode("utf-8").strip()
            ref_stat = _stat_token(ref)
            # The short name, as lineage has always recorded it (design D2).
            short = self.git("symbolic-ref", "--quiet", "--short", "HEAD", allow=(0, _NO_ANSWER))
            if short.returncode != _NO_ANSWER:
                branch = short.stdout.decode("utf-8").strip()
        racy = self._racy(read_at, (*watched, ref_stat))
        state = _State(watched, ref, ref_stat, branch, self._read_head(), racy)
        self._state = state
        return state

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


def _nul_separated(data: bytes) -> list[str]:
    return [item for item in data.decode("utf-8").split("\0") if item]


def _stat_token(path: Path) -> _Stat:
    try:
        info = os.stat(path)
    except (FileNotFoundError, NotADirectoryError):
        return None  # under reftable, refs/heads is a file, so a path below it is not a directory
    return (info.st_mtime_ns, info.st_size, info.st_ino)
