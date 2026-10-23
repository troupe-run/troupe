"""A run's workspace: its own worktree, or the theatre (spec: run-workspaces, stages;
worktree-stage design D1, D2, D7, D8, D10).

A worktree run works in a git worktree made for it at the theatre's HEAD, under
``.troupe/local/worktrees/<run id>``, through the VCS port, so any stage can use one: the local
stage runs the actor in it, and a Docker stage can mount it later. This module makes the worktree,
says when the theatre has changes the run won't see, snapshots the state every worktree of the
repository shares, captures the run's changes into the artifact store when it ends, and removes
the worktree when the person settles them.

A worktree contains nothing: the process can still write outside it, and what it does to the
repository's refs, config and hooks lands in the person's own repository. So a worktree never
changes what a stage enforces; troupe reports those shared changes, and discarding can't undo them.

Every operation here can read or write every file of the repository, so each is announced with
workspace.waiting once it has run for WORKSPACE_ANNOUNCE_AFTER_SECONDS, and is bounded by the VCS
adapter's own timeouts.
"""

import contextlib
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from troupe.core import defaults
from troupe.core.artifacts import ArtifactStore
from troupe.core.errors import TroupeError
from troupe.core.files import clone_file
from troupe.core.notices import Notice
from troupe.core.stores import local_dir
from troupe.core.vcs import Captured, SharedChanges, SharedState, Vcs

Kind = Literal["worktree", "theatre"]
Announce = Callable[[Notice], None]

_COPY_CHUNK_BYTES = 1024 * 1024


def worktrees_dir(theatre: Path) -> Path:
    return local_dir(theatre) / defaults.WORKTREES_DIR


def worktree_path(theatre: Path, run_id: str) -> Path:
    """Where the run ``run_id``'s worktree is, if it has one."""
    return worktrees_dir(theatre) / run_id


def relative(theatre: Path, path: Path) -> str:
    """``path`` relative to the theatre, with / separators, as events record it."""
    return path.relative_to(theatre).as_posix()


@contextlib.contextmanager
def announced(what: str, announce: Announce, after: float) -> Iterator[None]:
    """Announce ``what`` with workspace.waiting if it is still going after ``after`` seconds."""
    timer = threading.Timer(
        after,
        lambda: announce(
            Notice(
                "workspace.waiting",
                problem=f"troupe is still {what}, after {after:g}s.",
                fix="Nothing to do: a large repository takes longer. It stops at the version "
                "control adapter's timeout if something is holding it up.",
                details={"operation": what, "waitedSeconds": after},
            )
        ),
    )
    timer.daemon = True
    timer.start()
    try:
        yield
    finally:
        timer.cancel()


def worktree_base(vcs: Vcs, actor: str) -> tuple[str, str]:
    """The commit a worktree run starts from and the theatre's prefix in its repository, or a
    refusal: vcs.worktrees-unsupported, or workspace.no-head before the first commit."""
    prefix = vcs.theatre_prefix()  # refused here by an adapter that can't make worktrees
    base = vcs.head()
    if base is None:
        raise TroupeError(
            "workspace.no-head",
            problem=f"Actor {actor} works in its own worktree, made at HEAD, and this theatre "
            "has no commit yet.",
            fix=f"Commit your files first, or run {actor} in the theatre: troupe config set "
            f"actors.{actor}.workspace=theatre",
            details={"actor": actor},
        )
    return base, prefix


@dataclass(frozen=True)
class Worktree:
    """A run's worktree, made and filled."""

    path: Path
    base: str
    prefix: str
    dirty: tuple[str, ...]
    clones: tuple[str, ...]

    @property
    def cwd(self) -> Path:
        """Where the run works: the theatre's place in the worktree."""
        return self.path.joinpath(*self.prefix.rstrip("/").split("/")) if self.prefix else self.path

    def record(self, theatre: Path) -> dict[str, Any]:
        """The workspace as the run's start records it."""
        data: dict[str, Any] = {
            "kind": "worktree",
            "path": relative(theatre, self.path),
            "base": self.base,
            "dirty": bool(self.dirty),
            "clones": list(self.clones),
        }
        if self.prefix:
            data["prefix"] = self.prefix
        return data


def make_worktree(
    vcs: Vcs, theatre: Path, run_id: str, base: str, prefix: str, announce: Announce
) -> Worktree:
    """Make the run's worktree at ``base`` and fill it, saying first what the run won't see. On
    any failure, whatever part of it was made is removed again before the error is raised."""
    after = defaults.WORKSPACE_ANNOUNCE_AFTER_SECONDS
    with announced("looking for changes the run won't see", announce, after):
        differing = vcs.differing_from_head()
    # troupe's own state under .troupe/ is never the actor's to see, and is left out of the diff,
    # so only the person's other changes make the theatre dirty (worktree-stage design D2).
    troupe = f"{prefix}.troupe"
    dirty = tuple(p for p in differing if p != troupe and not p.startswith(f"{troupe}/"))
    if dirty:
        announce(_uncommitted(dirty, base))
    path = worktree_path(theatre, run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with announced("making the run's worktree", announce, after):
            vcs.add_worktree(path, base)
            filled = vcs.fill_worktree(path, clone_file, frozenset(differing))
    except BaseException:
        with contextlib.suppress(Exception):
            vcs.remove_worktree(path)
        raise
    return Worktree(path, base, prefix, dirty, filled.mechanisms)


def _uncommitted(dirty: tuple[str, ...], base: str) -> Notice:
    shown = list(dirty[: defaults.UNCOMMITTED_NOTICE_PATHS])
    return Notice(
        "workspace.uncommitted-unseen",
        problem=f"{len(dirty)} path(s) differ from HEAD ({base[:12]}), and the run won't see "
        "them: it works in its own worktree, made from HEAD. Accepting its changes may conflict "
        "with yours.",
        fix="Commit or stash your changes first if the run needs them. Otherwise, nothing to do.",
        details={"count": len(dirty), "paths": shown, "base": base},
    )


def shared_changed(changes: SharedChanges) -> Notice:
    """workspace.shared-git-changed, naming hooks first: a hook runs in the person's own
    repository on their next commit, push or checkout."""
    named = [
        *(f"hook {change.name} {change.change}" for change in changes.hooks),
        *(f"{change.name} {change.change}" for change in changes.refs),
        *(f"config file {change.name} {change.change}" for change in changes.config),
    ]
    hook_warning = (
        " A hook runs in your own repository the next time git uses it." if changes.hooks else ""
    )
    return Notice(
        "workspace.shared-git-changed",
        problem="While the run worked, the state every worktree of this repository shares "
        f"changed: {', '.join(named)}. Discarding the run won't undo it.{hook_warning}",
        fix="Look at each one before you go on: git branch, git tag, git stash list, git config "
        "--list --show-origin, and the hooks directory (git rev-parse --git-path hooks).",
        details=shared_data(changes),
    )


def shared_data(changes: SharedChanges) -> dict[str, Any]:
    """The shared changes as the run's end records them: each list that has something in it."""
    data: dict[str, Any] = {}
    for kind in ("refs", "config", "hooks"):
        entries = getattr(changes, kind)
        if entries:
            data[kind] = [{"name": entry.name, "change": entry.change} for entry in entries]
    return data


def snapshot(vcs: Vcs, announce: Announce) -> SharedState:
    with announced(
        "reading the repository's shared state", announce, defaults.WORKSPACE_ANNOUNCE_AFTER_SECONDS
    ):
        return vcs.shared_state()


def capture(
    vcs: Vcs,
    worktree: Worktree,
    artifacts: ArtifactStore,
    shared: SharedChanges,
    announce: Announce,
) -> dict[str, Any]:
    """The run's changes as its end records them: the diff stored as an artifact, with its
    counts, or the error that stopped the capture. The worktree is kept either way."""
    out = worktree.path.parent / f"{worktree.path.name}.diff"
    data: dict[str, Any]
    try:
        with announced(
            "capturing the run's changes", announce, defaults.WORKSPACE_ANNOUNCE_AFTER_SECONDS
        ):
            captured = vcs.capture(
                worktree.path, worktree.base, (f"{worktree.prefix}.troupe",), out
            )
            data = _counts(captured)
            if not captured.empty:
                data["diff"] = _store(out, artifacts)
    except TroupeError as error:
        data = {"error": error.to_data()}
    finally:
        with contextlib.suppress(FileNotFoundError):
            out.unlink()
    if not shared.empty:
        data["shared"] = shared_data(shared)
    return data


def _counts(captured: Captured) -> dict[str, Any]:
    return {
        "added": len(captured.added),
        "modified": len(captured.modified),
        "deleted": len(captured.deleted),
        "leftOut": len(captured.left_out),
    }


def _store(path: Path, artifacts: ArtifactStore) -> str:
    with artifacts.open_writer() as writer, path.open("rb") as reader:
        while chunk := reader.read(_COPY_CHUNK_BYTES):
            writer.write(chunk)
        return writer.finish()


def remove_worktree(vcs: Vcs, theatre: Path, run_id: str, announce: Announce) -> None:
    with announced(
        "removing the run's worktree", announce, defaults.WORKSPACE_ANNOUNCE_AFTER_SECONDS
    ):
        vcs.remove_worktree(worktree_path(theatre, run_id))
