"""What files a directory holds, as git would record them, for the audit of a run's changes (spec:
effects, "The audit sees changes as git sees them"; declared-effects design D4).

Each file is named by its path relative to the directory and identified by a git blob id, so two
states compare file by file without reading what git already knows:

- **A tree** (``at``): ``git ls-tree -r``, the blob ids it holds.
- **The working tree**: the index's blob ids (``git ls-files -s``), then every path ``git status``
  lists as changed or untracked, but not ignored, hashed as git would add it
  (``git hash-object --stdin-paths``, which applies the same filters ``git add`` does), or dropped
  when it's gone. Clean files cost nothing more than git's own status, and the person's index is
  read, never written.

Paths outside the directory, under its ``.troupe/``, and gitlinks (submodules) are left out.
"""

import os
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from troupe_vcs_git import GitAdapter

TROUPE = ".troupe"
GITLINK = "160000"


def _fields(data: bytes) -> list[str]:
    fields = data.decode("utf-8").split("\0")
    if fields and fields[-1] == "":
        fields.pop()
    return fields


class States:
    """File states, read through one adapter's git."""

    def __init__(self, adapter: "GitAdapter") -> None:
        self.adapter = adapter

    def _git(self, cwd: Path, *args: str, input: bytes | None = None) -> bytes:
        return self.adapter.git_in(
            cwd,
            *args,
            input=input,
            timeout=self.adapter.worktree_timeout,
            max_output_bytes=self.adapter.worktree_max_output_bytes,
        ).stdout

    def file_states(self, directory: Path, at: str | None = None) -> dict[str, str]:
        layout = self._git(directory, "rev-parse", "--show-toplevel", "--show-prefix")
        top_text, *rest = layout.decode("utf-8").splitlines()
        top, prefix = Path(top_text), rest[0] if rest else ""
        states = self._tree(top, at) if at is not None else self._working(top)
        return {
            relative: blob
            for path, blob in states.items()
            if (relative := _under(path, prefix)) is not None
        }

    def _tree(self, top: Path, at: str) -> dict[str, str]:
        found: dict[str, str] = {}
        for record in _fields(self._git(top, "ls-tree", "-r", "-z", "--full-tree", at)):
            meta, _, path = record.partition("\t")
            mode, kind, blob = meta.split(" ")
            if kind == "blob" and mode != GITLINK:
                found[path] = blob
        return found

    def _working(self, top: Path) -> dict[str, str]:
        found: dict[str, str] = {}
        for record in _fields(self._git(top, "ls-files", "-s", "-z", "--full-name")):
            meta, _, path = record.partition("\t")
            mode, blob, stage = meta.split(" ")
            if mode != GITLINK and stage == "0":
                found[path] = blob
        status = (
            "status",
            "--porcelain=v2",
            "-z",
            "--untracked-files=all",
            "--ignore-submodules=all",
        )
        dirty: list[str] = []
        fields = iter(_fields(self._git(top, *status)))
        for record in fields:
            kind = record[:1]
            if kind == "1":
                dirty.append(record.split(" ", 8)[8])
            elif kind == "2":
                dirty.append(record.split(" ", 9)[9])
                dirty.append(next(fields))  # the path it was renamed or copied from
            elif kind == "u":
                dirty.append(record.split(" ", 10)[10])
            elif kind == "?":
                dirty.append(record[2:])
        dirty = [path for path in dict.fromkeys(dirty) if not path.endswith("/")]
        present = [path for path in dirty if os.path.lexists(top.joinpath(*path.split("/")))]
        for path in dirty:
            found.pop(path, None)
        found.update(self._hash(top, present))
        return found

    def _hash(self, top: Path, paths: list[str]) -> Mapping[str, str]:
        """Each path's blob id, as ``git add`` would make it. One process for every path that
        fits a line; a path holding a newline is hashed on its own."""
        lined = [path for path in paths if "\n" not in path]
        hashed: dict[str, str] = {}
        if lined:
            out = self._git(
                top, "hash-object", "--stdin-paths", input="".join(f"{p}\n" for p in lined).encode()
            )
            hashed.update(zip(lined, out.decode("ascii").split(), strict=True))
        for path in paths:
            if "\n" in path:
                hashed[path] = self._git(top, "hash-object", "--", path).decode("ascii").strip()
        return hashed


def _under(path: str, prefix: str) -> str | None:
    """``path`` relative to the theatre at ``prefix``, or None when it's outside it or under its
    ``.troupe/``."""
    if not path.startswith(prefix):
        return None
    relative = path[len(prefix) :]
    if relative.split("/", 1)[0] == TROUPE:
        return None
    return relative
