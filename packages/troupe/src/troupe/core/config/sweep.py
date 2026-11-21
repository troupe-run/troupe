"""The sweep: reading hand edits to the config files back into config (spec: config-hand-edits;
hand-edit-sweep design D1, D3, D4, D5, D7).

Before a command uses config, holding the config files' lock, the sweep reads every config file
that isn't exactly what config renders, and works out each one's change: the values it holds
against what config holds for it (``changes.change`` on the part of the group the file owns, so
equal values give nothing and troupe's own writes never loop). It classifies each path (D3):

1. exactly what config renders: in line, not read;
2. a merge git made only from versions troupe wrote, still as git made it (a clean merge's bytes,
   or a conflicted file that still has its markers): not read, the merge rules apply;
3. conflict markers otherwise: not read, refused when the files are planned;
4. absent while config holds it: a removal;
5. anything else, an older version troupe wrote included: read (the file wins; owner,
   2026-11-21).

A staged write a recorded change vouches for is finished, never read as an edit (#60, D9). The
sweep is all or nothing: one file refused, and nothing from any file is recorded.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from troupe.core.config.changes import UNSET, Tree, apply, change
from troupe.core.config.kinds import ACTORS, CHARACTER, actor_files, staged_target
from troupe.core.config.projection import (
    Plan,
    file_hash,
    has_markers,
    merged_from_troupes,
    on_disk,
    refuse,
    render,
    troupes,
    written_by_flush,
)
from troupe.core.config.reading import (
    FileValues,
    invalid,
    owner,
    read_steady,
    read_values,
    refuse_file_problems,
)
from troupe.core.vcs import MergeSides

Entry = dict[str, Any]
Operation = tuple[tuple[str, ...], object]
Reader = Callable[[Path, str], bytes | None]


@dataclass(frozen=True)
class Edit:
    """One config file's hand edit: what it changes, and the file's hashes before and after."""

    path: str
    """The file, relative to .troupe/."""
    entries: tuple[Entry, ...]
    before: str | None
    """The hash of the file config rendered before the sweep, what troupe last had; None when
    config rendered no file."""
    after: str | None
    """The hash of the bytes read; None for a removal."""
    files: tuple[dict[str, str], ...]
    """The files the change vouches for: ``{path, hash}`` for one read, ``{path}`` for one
    removed."""


@dataclass(frozen=True)
class Swept:
    """What a sweep found."""

    edits: tuple[Edit, ...] = ()
    seen: dict[str, bytes | None] = field(default_factory=dict)
    """The bytes the sweep read for each config path it looked at, None for no file: what a write
    checks the file still holds (design D10)."""

    @property
    def entries(self) -> list[Entry]:
        return [entry for edit in self.edits for entry in edit.entries]


def sweep(
    troupe_dir: Path,
    config: Tree,
    recorded: Mapping[str, frozenset[str]],
    merged: Mapping[str, MergeSides],
    *,
    reader: Reader = read_steady,
) -> Swept:
    """The hand edits to the config files under ``troupe_dir`` (.troupe/), worked out against
    ``config``. ``recorded`` is every hash a change recorded for each file, and ``merged`` what
    the VCS says a merge combined into each. Refuses, recording nothing, an unknown file or a file
    that can't be read as config."""
    disk = on_disk(troupe_dir)
    refuse(Plan((), disk.unknown))
    rendered = render(config)
    vouched = dict(recorded)
    for path, written in written_by_flush(troupe_dir).items():
        vouched[path] = vouched.get(path, frozenset()) | written
    finishing = {
        target
        for staged, data in disk.staged.items()
        if (target := staged_target(staged)) is not None and troupes(target, data, vouched)
    }
    seen: dict[str, bytes | None] = {}
    reads: list[FileValues] = []
    removed: list[str] = []
    for path in sorted(rendered.keys() | disk.files.keys()):
        if path in finishing:
            continue
        have = reader(troupe_dir, path)
        seen[path] = have
        if have == rendered.get(path):
            continue
        if have is None:
            removed.append(path)
            continue
        merge = merged.get(path)
        markers = has_markers(have)
        if (
            merge is not None
            and (merge.kind == "clean" or markers)
            and merged_from_troupes(path, have, merge, vouched)
        ):
            continue
        if markers:
            continue
        reads.append(read_values(path, have, troupe_dir / path))
    present = {path for path, data in seen.items() if data is not None} | finishing
    operations = _operations(config, reads, removed, present, troupe_dir)
    edits = _edits(config, rendered, operations, seen)
    refuse_file_problems(
        reads, apply(config, [e for edit in edits for e in edit.entries]), troupe_dir
    )
    return Swept(tuple(edits), seen)


def _operations(
    config: Tree,
    reads: Sequence[FileValues],
    removed: Sequence[str],
    present: set[str],
    troupe_dir: Path,
) -> dict[str, list[Operation]]:
    """What each file sets or unsets: a fields file its group whole (keeping the character), a
    character file the character, and a deleted file what it held (design D4, D5)."""
    found: dict[str, list[Operation]] = {}
    for read in reads:
        kind, name = read.group
        if read.owns == "character":
            found[read.path] = [((kind, name, CHARACTER), read.values[CHARACTER])]
            continue
        group = dict(read.values)
        existing = config.get(kind, {}).get(name)
        if isinstance(existing, Mapping) and CHARACTER in existing:
            group[CHARACTER] = existing[CHARACTER]
        found[read.path] = [((kind, name), group)]
    gone = set(removed)
    for path in removed:
        located = owner(path)
        if located is None:
            continue
        (kind, name), holds = located
        if holds == "character":
            if kind == ACTORS and actor_files(name)[0] in gone:
                continue  # the actor goes whole, with its .yaml file
            found[path] = [((kind, name, CHARACTER), UNSET)]
            continue
        if kind == ACTORS and actor_files(name)[1] in present:
            md = actor_files(name)[1]
            error = invalid(
                md,
                "invalid",
                f"its actor's .yaml file, .troupe/{path}, was deleted, and an actor needs it",
                "Restore the .yaml file, or delete this file too to remove the actor.",
            )
            error.path = str(troupe_dir / md)
            raise error
        found[path] = [((kind, name), UNSET)]
    return found


def _edits(
    config: Tree,
    rendered: Mapping[str, bytes],
    operations: Mapping[str, list[Operation]],
    seen: Mapping[str, bytes | None],
) -> list[Edit]:
    """Each file's edit, in path order, each worked out on the config the ones before it leave."""
    current = config
    edits: list[Edit] = []
    for path in sorted(operations):
        entries = change(current, operations[path])
        if not entries:
            continue
        current = apply(current, entries)
        data = seen.get(path)
        before = rendered.get(path)
        files: list[dict[str, str]] = []
        if data is not None:
            files.append({"path": path, "hash": file_hash(data)})
        else:
            files.append({"path": path})
            located = owner(path)
            if located is not None and located[0][0] == ACTORS and located[1] == "fields":
                md = actor_files(located[0][1])[1]
                if md in rendered and seen.get(md, b"") is None:
                    files.append({"path": md})
        edits.append(
            Edit(
                path,
                tuple(entries),
                file_hash(before) if before is not None else None,
                file_hash(data) if data is not None else None,
                tuple(files),
            )
        )
    return edits
