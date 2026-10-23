"""The git adapter's merge sides (spec: vcs; config-projection-conflicts design D2, D3).

A path git left unmerged is read from the index's stages: 2 is ours and 3 is theirs, and a stage
the index doesn't list is a side with no file. That covers whatever left it unmerged: a merge, a
rebase, a cherry-pick, a revert or a stash pop.

A path git merged cleanly is looked for only in the merge in progress (``MERGE_HEAD``, with the
index's stage-0 blob as what the merge gave) or in HEAD when it is a merge of two parents (with
HEAD's blob). A path counts only when its merged blob differs from both parents' blobs, since one
equal to a side is already that side, and only when ``git merge-tree --write-tree`` on the two
parents reproduces it exactly, with no conflict. merge-tree redoes the merge with git's own strategy
and the person's merge settings, and writes nothing but unreachable objects. So a merge someone
edited before committing it, or made with options merge-tree didn't get, is left out. Octopus merges
are left out too.

Paths are theatre-relative: ls-files and ls-tree print them relative to the directory git runs in,
which is the theatre, while merge-tree names conflicted paths from the repository's top.
"""

from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING

from troupe.core.vcs import MergeSides
from troupe.platform.processes import Completed

if TYPE_CHECKING:
    from troupe_vcs_git import GitAdapter

_MERGED, _OURS, _THEIRS = "0", "2", "3"
_CONFLICTS = 1
"""merge-tree's exit status when the merge has conflicts: an answer, not a failure."""


def _records(data: bytes) -> list[str]:
    return [record for record in data.decode("utf-8").split("\0") if record]


def _index(data: bytes) -> list[tuple[str, str, str]]:
    """Each ``<mode> <object> <stage>\\t<path>`` record, as ls-files -s and -u print them, as
    (path, stage, object)."""
    entries = []
    for record in _records(data):
        info, _, path = record.partition("\t")
        _mode, blob, stage = info.split(" ")
        entries.append((path, stage, blob))
    return entries


def _tree(data: bytes) -> dict[str, str]:
    """Each blob in ``<mode> <type> <object>\\t<path>`` records, as ls-tree prints them, by path."""
    blobs: dict[str, str] = {}
    for record in _records(data):
        info, _, path = record.partition("\t")
        _mode, kind, blob = info.split(" ")
        if kind == "blob":
            blobs[path] = blob
    return blobs


class Merges:
    """Merge sides, read through one adapter's git."""

    def __init__(self, adapter: "GitAdapter") -> None:
        self.adapter = adapter

    def under(self, directory: str) -> dict[str, MergeSides]:
        found = self._conflicted(directory)
        for path, sides in self._clean(directory).items():
            found.setdefault(path, sides)
        return found

    def _conflicted(self, directory: str) -> dict[str, MergeSides]:
        unmerged = _index(self.adapter.git("ls-files", "-u", "-z", "--", directory).stdout)
        stages: dict[str, dict[str, str]] = {}
        for path, stage, blob in unmerged:
            stages.setdefault(path, {})[stage] = blob
        blobs = self._read(
            blob for by_stage in stages.values() for s, blob in by_stage.items() if s != "1"
        )
        return {
            path: MergeSides(
                "conflicted",
                tuple(blobs.get(by_stage.get(stage, "")) for stage in (_OURS, _THEIRS)),
            )
            for path, by_stage in sorted(stages.items())
        }

    def _merge(self, directory: str) -> tuple[tuple[str, str], Mapping[str, str]] | None:
        """The merge to look at: its two parents, and the blob it gave each path under
        ``directory``. The merge in progress, else HEAD's merge commit, else None."""
        if self.adapter.head() is None:
            return None
        named = self.adapter.git("rev-parse", "--git-path", "MERGE_HEAD").stdout.decode().strip()
        merge_head = self.adapter.theatre / Path(named)  # an absolute path stays as it is
        if merge_head.is_file():
            theirs = merge_head.read_text(encoding="ascii").split()
            if len(theirs) != 1:
                return None  # an octopus merge in progress
            staged = _index(self.adapter.git("ls-files", "-s", "-z", "--", directory).stdout)
            return ("HEAD", theirs[0]), {p: blob for p, stage, blob in staged if stage == _MERGED}
        parents = self.adapter.git("rev-parse", "HEAD^@").stdout.decode("ascii").split()
        if len(parents) != 2:
            return None
        merged = _tree(self.adapter.git("ls-tree", "-r", "-z", "HEAD", "--", directory).stdout)
        return (parents[0], parents[1]), merged

    def _clean(self, directory: str) -> dict[str, MergeSides]:
        merge = self._merge(directory)
        if merge is None:
            return {}
        parents, merged = merge
        sides = [
            _tree(self.adapter.git("ls-tree", "-r", "-z", parent, "--", directory).stdout)
            for parent in parents
        ]
        candidates = {
            path: blob for path, blob in merged.items() if all(s.get(path) != blob for s in sides)
        }
        if not candidates:
            return {}
        redone = self.adapter.git(
            "merge-tree", "--write-tree", "-z", *parents, allow=(0, _CONFLICTS)
        )
        tree, *rest = redone.stdout.decode("utf-8").split("\0")
        prefix = self.adapter.theatre_prefix()
        conflicted: set[str] = set()
        for record in rest:
            if not record:
                break  # the end of the conflicted entries: the messages follow
            path = record.partition("\t")[2]
            if path.startswith(prefix):
                conflicted.add(path[len(prefix) :])
        again = _tree(self.adapter.git("ls-tree", "-r", "-z", tree, "--", directory).stdout)
        reproduced = {
            path: blob
            for path, blob in candidates.items()
            if path not in conflicted and again.get(path) == blob
        }
        blobs = self._read(
            [*reproduced.values(), *(s[path] for s in sides for path in reproduced if path in s)]
        )
        return {
            path: MergeSides("clean", tuple(blobs.get(s.get(path, "")) for s in sides), blobs[blob])
            for path, blob in sorted(reproduced.items())
        }

    def _read(self, objects: Iterable[str]) -> dict[str, bytes]:
        """Each blob's bytes, read with one ``git cat-file --batch``."""
        wanted = list(dict.fromkeys(objects))
        if not wanted:
            return {}
        argv = ("cat-file", "--batch")
        out = self.adapter.git_in(
            self.adapter.theatre,
            *argv,
            input="".join(f"{blob}\n" for blob in wanted).encode("ascii"),
            timeout=self.adapter.timeout,
            max_output_bytes=self.adapter.max_output_bytes,
        ).stdout
        blobs: dict[str, bytes] = {}
        at = 0
        for blob in wanted:
            end = out.index(b"\n", at)
            header = out[at:end].decode("ascii").split(" ")
            if len(header) != 3 or header[:2] != [blob, "blob"]:
                problem = Completed(0, b"", f"expected the blob {blob}, got {header}".encode())
                raise self.adapter.failed(["git", *argv], problem)
            size = int(header[2])
            blobs[blob] = out[end + 1 : end + 1 + size]
            at = end + 1 + size + 1  # the newline after each object
        return blobs
