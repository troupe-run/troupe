"""troupe's plain filesystem VCS adapter: no branches, everything committed (design D1).

For a theatre with no version control. There is no branch, no HEAD and no configured identity, and
every file counts as committed, so nothing is ever left out as being from another branch. It runs no
commands, so it declares no environment policy (design D11).

It can't make a worktree, so each worktree operation is refused with vcs.worktrees-unsupported, and
with nothing shared between worktrees, its shared state is empty (worktree-stage design D4, D10).
With no merges, it reports no merge sides (config-projection-conflicts design D2), and with no
index it marks nothing resolved (mark-config-resolved design D4). Every directory counts as being in
a repository, so troupe init can make a theatre anywhere (init-and-audition design D7).
"""

import hashlib
import os
from collections.abc import Hashable, Mapping
from pathlib import Path, PurePosixPath
from typing import NoReturn

from troupe.core.vcs import (
    Applicability,
    Captured,
    Clone,
    Filled,
    Marked,
    MergeSides,
    Resolve,
    SharedState,
    worktrees_unsupported,
)

NAME = "files"


class FilesAdapter:
    """The VCS port for a theatre with no version control."""

    def __init__(self, theatre: Path) -> None:
        self.theatre = theatre

    @property
    def name(self) -> str:
        return NAME

    def check_repository(self) -> None:
        return None

    def branch(self) -> str | None:
        return None

    def head(self) -> str | None:
        return None

    def branch_token(self) -> Hashable:
        return None

    def committed_under(self, directory: str) -> frozenset[str]:
        base = self.theatre / directory
        if not base.is_dir():
            return frozenset()
        return frozenset(
            path.relative_to(self.theatre).as_posix() for path in base.rglob("*") if path.is_file()
        )

    def merge_sides_under(self, directory: str) -> Mapping[str, MergeSides]:
        del directory
        return {}

    def mark_resolved(self, paths: Mapping[str, Resolve]) -> Marked:
        return Marked(dict.fromkeys(paths, "no-index"))

    def configured_identities(self) -> tuple[str, ...]:
        return ()

    def _unsupported(self) -> NoReturn:
        raise worktrees_unsupported(NAME)

    def theatre_prefix(self) -> str:
        self._unsupported()

    def differing_from_head(self) -> tuple[str, ...]:
        self._unsupported()

    def add_worktree(self, path: Path, at: str) -> None:
        self._unsupported()

    def fill_worktree(self, path: Path, clone: Clone, skip: frozenset[str]) -> Filled:
        self._unsupported()

    def capture(self, path: Path, baseline: str, leave_out: tuple[str, ...], out: Path) -> Captured:
        self._unsupported()

    def check_apply(self, diff: Path) -> Applicability:
        self._unsupported()

    def apply(self, diff: Path) -> tuple[str, ...]:
        self._unsupported()

    def remove_worktree(self, path: Path) -> None:
        self._unsupported()

    def shared_state(self) -> SharedState:
        return SharedState()

    def file_states(self, directory: Path, at: str | None = None) -> Mapping[str, str]:
        """Every file under ``directory``, by a SHA-256 of its bytes (a link's, of its target's
        text): with no ignore rules, it records everything but ``.git`` and ``.troupe/``. With no
        history, ``at`` names nothing it could read (declared-effects design D4)."""
        if at is not None:
            self._unsupported()
        found: dict[str, str] = {}
        for here, dirnames, filenames in os.walk(directory, followlinks=False):
            relative = PurePosixPath(*Path(here).relative_to(directory).parts)
            if not relative.parts:
                dirnames[:] = [d for d in dirnames if d not in (".git", ".troupe")]
                filenames = [f for f in filenames if f not in (".git", ".troupe")]
            for name in filenames:
                path = Path(here) / name
                if path.is_symlink():
                    data = os.readlink(path).encode("utf-8", "surrogateescape")
                elif path.is_file():
                    data = path.read_bytes()
                else:
                    continue
                found[(relative / name).as_posix()] = hashlib.sha256(data).hexdigest()
        return found
