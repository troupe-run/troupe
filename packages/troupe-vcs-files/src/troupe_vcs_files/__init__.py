"""troupe's plain filesystem VCS adapter: no branches, everything committed (design D1).

For a theatre with no version control. There is no branch, no HEAD and no configured identity, and
every file counts as committed, so nothing is ever left out as being from another branch. It runs no
commands, so it declares no environment policy (design D11).
"""

from collections.abc import Hashable
from pathlib import Path


class FilesAdapter:
    """The VCS port for a theatre with no version control."""

    def __init__(self, theatre: Path) -> None:
        self.theatre = theatre

    @property
    def name(self) -> str:
        return "files"

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
