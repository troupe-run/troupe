"""troupe's plain filesystem VCS adapter: no branches, everything committed (design D1).

For a theatre with no version control. There is no branch, no HEAD and no configured identity, and
every file counts as committed, so nothing is ever left out as being from another branch. It runs no
commands, so it declares no environment policy (design D11).

It can't make a worktree, so each worktree operation is refused with vcs.worktrees-unsupported, and
with nothing shared between worktrees, its shared state is empty (worktree-stage design D4, D10).
"""

from collections.abc import Hashable
from pathlib import Path
from typing import NoReturn

from troupe.core.vcs import (
    Applicability,
    Captured,
    Clone,
    Filled,
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
