"""The version-control port (spec: vcs; event-store design D1, D4, D7).

troupe reads the working tree's state only through a VCS adapter: the branch, HEAD, which files are
committed, and the identity the VCS is configured with. Adapters are separately packaged and found
by name through the ``troupe.vcs`` entry point group (load_vcs); troupe never imports one.

Paths given to and returned by an adapter are relative to the theatre, with ``/`` separators, except
where the worktree operations say otherwise.

The worktree operations (worktree-stage design D4, D10) are what a run's own worktree needs: a
checkout of HEAD made for one run, its changes captured as a diff, the diff applied to the theatre,
and the worktree removed. A theatre can sit in a subdirectory of its repository, so these speak in
paths relative to the repository's top level, and ``theatre_prefix`` says where the theatre is in
it. An adapter that can't make worktrees refuses each of them with vcs.worktrees-unsupported
(``worktrees_unsupported``).
"""

import importlib.metadata
import os
from collections.abc import Callable, Hashable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol

from troupe.core.errors import TroupeError

ENTRY_POINT_GROUP = "troupe.vcs"


Clone = Callable[[Path, Path], str]
"""Clones a file (the theatre's) to a path in a worktree and returns the mechanism it used:
troupe.platform.clones.clone_file, given through the core so adapters stay off the platform."""


@dataclass(frozen=True)
class Filled:
    """How a worktree's files were written."""

    mechanisms: tuple[str, ...]
    """The clone mechanisms used, sorted, each once: empty when every file was checked out."""
    cloned: int
    checked_out: int
    baseline: str
    """The tree of the worktree as the run starts, as the VCS sees it: what its diff is from."""


@dataclass(frozen=True)
class Captured:
    """What a worktree's diff holds, by repository-relative path, and what was left out of it."""

    added: tuple[str, ...]
    modified: tuple[str, ...]
    deleted: tuple[str, ...]
    left_out: tuple[str, ...]

    @property
    def empty(self) -> bool:
        return not (self.added or self.modified or self.deleted)


@dataclass(frozen=True)
class Applicability:
    """Whether a diff applies to the theatre's working tree: the files it changes, and those of them
    that don't apply cleanly (none, when it applies)."""

    files: tuple[str, ...]
    failing: tuple[str, ...]

    @property
    def applies(self) -> bool:
        return not self.failing


SharedKind = Literal["refs", "config", "hooks"]
Change = Literal["added", "changed", "removed"]


@dataclass(frozen=True)
class SharedChange:
    name: str
    change: Change


@dataclass(frozen=True)
class SharedChanges:
    """What changed between two snapshots of the state every worktree shares (design D10)."""

    refs: tuple[SharedChange, ...] = ()
    config: tuple[SharedChange, ...] = ()
    hooks: tuple[SharedChange, ...] = ()

    @property
    def empty(self) -> bool:
        return not (self.refs or self.config or self.hooks)


def _compare(before: Mapping[str, str], after: Mapping[str, str]) -> tuple[SharedChange, ...]:
    changes = [
        SharedChange(
            name, "added" if name not in before else "removed" if name not in after else "changed"
        )
        for name in sorted(before.keys() | after.keys())
        if before.get(name) != after.get(name)
    ]
    return tuple(changes)


@dataclass(frozen=True)
class SharedState:
    """The state a repository's worktrees share: each ref and what it points to, each config file's
    hash, and each hook's hash and mode. An adapter with no shared state gives an empty one."""

    refs: Mapping[str, str] = field(default_factory=dict)
    config: Mapping[str, str] = field(default_factory=dict)
    hooks: Mapping[str, str] = field(default_factory=dict)

    def compare(self, after: "SharedState") -> SharedChanges:
        return SharedChanges(
            refs=_compare(self.refs, after.refs),
            config=_compare(self.config, after.config),
            hooks=_compare(self.hooks, after.hooks),
        )


def worktrees_unsupported(adapter: str) -> TroupeError:
    """vcs.worktrees-unsupported, for an adapter that can't make worktrees."""
    return TroupeError(
        "vcs.worktrees-unsupported",
        problem=f"The {adapter!r} version-control adapter can't make a worktree, so a run can't "
        "work in one of its own.",
        fix="Run the actor in the theatre instead: troupe config set "
        "actors.<name>.workspace=theatre, or keep the theatre in git.",
        details={"adapter": adapter},
    )


class Vcs(Protocol):
    """What troupe needs to know about version control. Callers depend only on this."""

    @property
    def name(self) -> str:
        """The adapter's name, as lineage records it: ``git`` or ``files``."""
        ...

    def branch(self) -> str | None:
        """The checked-out branch; None when HEAD is detached or there are no branches.

        It is the branch at the time of the call. An adapter may answer from a cache only while
        its branch token is unchanged (cache-vcs-state design D5).
        """
        ...

    def head(self) -> str | None:
        """The HEAD commit; None before the first commit or without version control.

        It is HEAD at the time of the call, cached only as ``branch`` may be.
        """
        ...

    def branch_token(self) -> Hashable:
        """A cheap value that changes whenever the branch, HEAD or what is committed changes.

        It changes whichever process made the change. Reading it runs no command while nothing has
        moved, so a caller asks for the branch again only when the token changes (event-store
        design D4). An adapter that can't promise this returns a value that never compares equal,
        such as a fresh ``object()``, which turns its callers' caching off (cache-vcs-state D5).
        """
        ...

    def committed_under(self, directory: str) -> frozenset[str]:
        """Every committed file under ``directory``: in HEAD or the index (staged counts).

        A committed file no longer travels with a branch switch; an uncommitted one does.
        """
        ...

    def configured_identities(self) -> tuple[str, ...]:
        """The identity the VCS is configured with, from its most specific setting.

        Empty when none is set (or it is set empty). More than one value means the setting is
        ambiguous, and the caller must refuse rather than pick one.
        """
        ...

    # The worktree operations (worktree-stage design D4). Paths are repository-relative.

    def theatre_prefix(self) -> str:
        """Where the theatre is in its repository: ``""`` at the top, else ``"sub/dir/"``."""
        ...

    def differing_from_head(self) -> tuple[str, ...]:
        """The paths that differ from HEAD: staged, unstaged, and untracked but not ignored."""
        ...

    def add_worktree(self, path: Path, at: str) -> None:
        """Register an empty worktree at ``path``, detached at commit ``at``, writing no file."""
        ...

    def fill_worktree(self, path: Path, clone: Clone, skip: frozenset[str]) -> Filled:
        """Write HEAD's files into the worktree at ``path``: clone each from the theatre with
        ``clone``, except those in ``skip``, check out the rest, then check out again from the VCS
        each file that differs from HEAD. Returns the baseline its diff is taken from."""
        ...

    def capture(self, path: Path, baseline: str, leave_out: tuple[str, ...], out: Path) -> Captured:
        """Write the worktree's changes since ``baseline`` (from fill_worktree) to ``out`` as a
        binary diff, leaving out the paths under each of ``leave_out``. Everything the VCS doesn't
        ignore counts."""
        ...

    def check_apply(self, diff: Path) -> Applicability:
        """Whether the diff at ``diff`` applies cleanly to the theatre's working tree."""
        ...

    def apply(self, diff: Path) -> tuple[str, ...]:
        """Apply the diff at ``diff`` to the working tree, unstaged, all or nothing; the files it
        changed. Refused, changing nothing, when any part doesn't apply."""
        ...

    def remove_worktree(self, path: Path) -> None:
        """Remove the worktree at ``path`` and its registration, also when the directory is
        already gone."""
        ...

    def shared_state(self) -> SharedState:
        """A snapshot of what every worktree of the repository shares (design D10)."""
        ...


def is_committed(vcs: Vcs, path: str) -> bool:
    """Whether the theatre-relative ``path`` is committed."""
    parent = path.rpartition("/")[0] or "."
    return path in vcs.committed_under(parent)


def installed_adapters() -> dict[str, importlib.metadata.EntryPoint]:
    return {ep.name: ep for ep in importlib.metadata.entry_points(group=ENTRY_POINT_GROUP)}


def load_vcs(name: str, theatre: str | os.PathLike[str]) -> Vcs:
    """The VCS adapter registered as ``name``, for the theatre at ``theatre``."""
    adapters = installed_adapters()
    if name not in adapters:
        installed = ", ".join(sorted(adapters)) or "none"
        raise TroupeError(
            "vcs.unknown-adapter",
            problem=f"No version-control adapter named {name!r} is installed "
            f"(installed: {installed}).",
            fix="Use one of the installed adapters, or install the package that provides this one.",
            details={"adapter": name, "installed": sorted(adapters)},
        )
    factory = adapters[name].load()
    vcs: Vcs = factory(Path(theatre))
    return vcs
