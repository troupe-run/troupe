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

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from troupe.core import strict_json
from troupe.core.config.changes import UNSET, Rename, Tree, apply, change
from troupe.core.config.kinds import ACTORS, CHARACTER, actor_files, staged_target
from troupe.core.config.moves import Pair, pair_moves
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
from troupe.core.errors import TroupeError
from troupe.core.notices import Notice
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
    read: frozenset[str] = frozenset()
    """The files whose values the sweep read: a person's files, which a write changes surgically
    (design D6)."""
    refused: frozenset[str] = frozenset()
    """With ``force``, the files the sweep couldn't read as config: replaced with what config
    says, keeping a copy, and nothing recorded from them (design D11)."""
    notices: tuple[Notice, ...] = ()
    """What the sweep has to say about itself, such as an unreadable record of present files."""
    own_first: bool = False
    """Whether the command's own change goes first, before these edits: a rename of files a
    person already moved, whose edits were worked out against the renamed config (config-mv
    design D5)."""

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
    force: bool = False,
    config_before: Tree | None = None,
) -> Swept:
    """The hand edits to the config files under ``troupe_dir`` (.troupe/), worked out against
    ``config``. ``recorded`` is every hash a change recorded for each file, and ``merged`` what
    the VCS says a merge combined into each. Refuses, recording nothing, an unknown file or a file
    that can't be read as config; with ``force``, such a file is set aside instead (``refused``),
    and the others are still read. With ``config_before`` (config before a rename the command
    records first), a file whose values are what that config held for it is in line too: it's the
    person's file, unchanged but for the rename, so it's written back surgically and records
    nothing (config-mv design D5, review of #505)."""
    disk = on_disk(troupe_dir)
    refuse(Plan((), disk.unknown))
    remembered, notices = present_at_last_sync(troupe_dir)
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
    unchanged: set[str] = set()
    refused: set[str] = set()
    reads: list[FileValues] = []
    removed: list[str] = []
    for path in sorted(rendered.keys() | disk.files.keys()):
        if path in finishing:
            continue
        have = seen[path] = reader(troupe_dir, path)
        if config_before is not None and _holds_as_before(path, have, config_before):
            unchanged.add(path)
            continue
        kind = _classify(path, have, rendered.get(path), merged.get(path), vouched, remembered)
        if kind == "removed":
            removed.append(path)
        elif kind == "read" and have is not None:
            read = _read(troupe_dir, path, have, force=force)
            if read is None:
                refused.add(path)
            else:
                reads.append(read)
    present = {path for path, data in seen.items() if data is not None} | finishing
    read_paths = frozenset(r.path for r in reads) | unchanged
    found, move_notices = _moves_aside(config, reads, removed)
    edits = _checked_edits(troupe_dir, config, rendered, found, present, seen, refused, force)
    return Swept(tuple(edits), seen, read_paths, frozenset(refused), (*notices, *move_notices))


def _classify(
    path: str,
    have: bytes | None,
    want: bytes | None,
    merge: MergeSides | None,
    vouched: Mapping[str, frozenset[str]],
    remembered: frozenset[str],
) -> str:
    """What the sweep does with one config path (design D3): ``skip`` it, read it as ``removed``,
    or ``read`` its values."""
    if have == want:
        return "skip"
    if have is None:
        # Removed only when this clone had it at its last sync; otherwise written again.
        return "removed" if path in remembered else "skip"
    # A file git holds conflicted is still being resolved while any marker line is left in it;
    # any other file only with a whole conflict in it.
    conflicted = merge is not None and merge.kind == "conflicted"
    markers = (conflicted and _any_marker(have)) or has_markers(have)
    if (
        merge is not None
        and (merge.kind == "clean" or markers)
        and merged_from_troupes(path, have, merge, vouched)
    ):
        return "skip"  # still as git made it: the merge rules apply
    return "skip" if markers else "read"


def _read(troupe_dir: Path, path: str, data: bytes, *, force: bool) -> FileValues | None:
    """The file's values, or None when ``force`` sets aside a file that can't be read."""
    try:
        return read_values(path, data, troupe_dir / path)
    except TroupeError as error:
        if not (force and error.code == "config.file-invalid"):
            raise
        return None


@dataclass
class _Found:
    """What the sweep found to work edits out from: the files read and removed (hand moves
    aside), the hand moves, and whether a new actor's .yaml arrived."""

    reads: list[FileValues]
    removed: list[str]
    pairs: list[Pair]
    arrived: bool


def _holds_as_before(path: str, have: bytes | None, config: Tree) -> bool:
    """Whether the config file at ``path`` holds exactly the values ``config`` held for it."""
    from troupe.core.config.reading import owned

    located = owner(path)
    if have is None or located is None:
        return False
    (kind, name), _ = located
    group = config.get(kind, {}).get(name)
    if not isinstance(group, Mapping):
        return False
    try:
        values = read_values(path, have).values
    except TroupeError:
        return False
    return values == owned(path, group)


def _moves_aside(
    config: Tree, reads: list[FileValues], removed: list[str]
) -> tuple["_Found", list[Notice]]:
    """Hand moves first: an entity's files gone and another's arrived with the same values are a
    rename, not a removal and an addition (config-mv design D6). The files they pair are set
    aside from the reads and removals the rest of the sweep works edits out from."""
    pairs, notices = pair_moves(config, reads, removed)
    moved_in = {read.path for pair in pairs for read in pair.arrived}
    moved_out = {path for pair in pairs for path in pair.gone}
    arrived = any(
        r.group[0] == ACTORS and r.owns == "fields" and r.group[1] not in config.get(ACTORS, {})
        for r in reads
    )
    found = _Found(
        [read for read in reads if read.path not in moved_in],
        [path for path in removed if path not in moved_out],
        pairs,
        arrived,
    )
    return found, notices


def _checked_edits(
    troupe_dir: Path,
    config: Tree,
    rendered: Mapping[str, bytes],
    found: _Found,
    present: set[str],
    seen: Mapping[str, bytes | None],
    refused: set[str],
    force: bool,
) -> list[Edit]:
    """Each file's edit, once the config they make together breaks no rule in a file read; with
    ``force``, a file whose values break one is set aside and the rest worked out again."""
    reads = found.reads
    while True:
        operations = _operations(config, found, present, troupe_dir)
        edits = _edits(config, rendered, operations, seen, {p.main: p for p in found.pairs})
        entries = [entry for edit in edits for entry in edit.entries]
        try:
            refuse_file_problems(reads, apply(config, entries), troupe_dir)
        except TroupeError as error:
            bad = next((r for r in reads if error.path == str(troupe_dir / r.path)), None)
            if not force or bad is None:
                raise
            reads.remove(bad)
            refused.add(bad.path)
            continue
        return edits


def _operations(
    config: Tree, files: _Found, present: set[str], troupe_dir: Path
) -> dict[str, list[Operation]]:
    """What each file sets or unsets: a fields file its group whole (keeping the character), a
    character file the character, a deleted file what it held (design D4, D5), and a hand move
    the rename, keyed by the new entity's main file (config-mv design D6)."""
    reads, removed = files.reads, files.removed
    found: dict[str, list[Operation]] = {
        pair.main: [((pair.kind, pair.new), Rename((pair.kind, pair.old)))] for pair in files.pairs
    }
    for read in reads:
        kind, name = read.group
        if read.owns == "character":
            found[read.path] = [((kind, name, CHARACTER), read.values[CHARACTER])]
            continue
        # The group whole from the file's values; its character, which the .yaml doesn't own, is
        # kept as the edits before this one leave it (_edits fills it in).
        found[read.path] = [((kind, name), _FieldsOf(dict(read.values)))]
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
                "Restore the .yaml file, or delete this file too to remove the actor."
                + (
                    " If you moved the actor, move this file with its .yaml, or rename it with "
                    "troupe config mv."
                    if files.arrived
                    else ""
                ),
            )
            error.path = str(troupe_dir / md)
            raise error
        found[path] = [((kind, name), UNSET)]
    return found


class _FieldsOf(dict[str, Any]):
    """A fields file's values: the group whole but its character, which ``_resolved`` keeps."""


def _resolved(current: Mapping[str, Any], operation: Operation) -> Operation:
    """``operation``, with a fields file's group given the character ``current`` holds."""
    path, value = operation
    if not isinstance(value, _FieldsOf):
        return operation
    group = dict(value)
    existing = current.get(path[0], {}).get(path[1])
    if isinstance(existing, Mapping) and CHARACTER in existing:
        group[CHARACTER] = existing[CHARACTER]
    return path, group


def _edits(
    config: Tree,
    rendered: Mapping[str, bytes],
    operations: Mapping[str, list[Operation]],
    seen: Mapping[str, bytes | None],
    pairs: Mapping[str, Pair],
) -> list[Edit]:
    """Each file's edit, in path order, each worked out on the config the ones before it leave."""
    current = config
    edits: list[Edit] = []
    for path in sorted(operations):
        entries = change(current, [_resolved(current, op) for op in operations[path]])
        if not entries:
            continue
        current = apply(current, entries)
        pair = pairs.get(path)
        if pair is not None:
            edits.append(_move(pair, entries, rendered, seen))
            continue
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


def _move(
    pair: Pair,
    entries: Sequence[Entry],
    rendered: Mapping[str, bytes],
    seen: Mapping[str, bytes | None],
) -> Edit:
    """A hand move's edit: the rename, the new files read and the old ones gone, with the new main
    file as its source, from the old main file as config rendered it (config-mv design D6)."""
    old_main = pair.gone[0]
    files = [
        {"path": read.path, "hash": file_hash(data)}
        for read in pair.arrived
        if (data := seen.get(read.path)) is not None
    ]
    files += [{"path": path} for path in pair.gone]
    before = rendered.get(old_main)
    after = seen.get(pair.main)
    return Edit(
        pair.main,
        tuple(entries),
        file_hash(before) if before is not None else None,
        file_hash(after) if after is not None else None,
        tuple(sorted(files, key=lambda f: f["path"])),
    )


_MARKER_LINE = re.compile(rb"^(<<<<<<< |=======\r?$|>>>>>>> )", re.MULTILINE)


def _any_marker(data: bytes) -> bool:
    """Whether ``data`` holds any of git's conflict marker lines."""
    return _MARKER_LINE.search(data) is not None


PRESENT = "local/config/present.json"
"""This clone's record of the config files there were when it last synced: a file that was, and
isn't now, a person deleted; a file that never was here is written again, never read as a
removal (hand-edit-sweep design D4). Kept out of git, like everything under local/."""


def present_at_last_sync(troupe_dir: Path) -> tuple[frozenset[str], list[Notice]]:
    """The config files there were at this clone's last sync: none before its first. A record
    that can't be read counts as none, so every missing file is written again rather than read as
    a removal, and a notice names it (design D4)."""
    path = troupe_dir / PRESENT
    if not path.is_file():
        return frozenset(), []
    try:
        found = strict_json.loads(path.read_bytes())
        if not isinstance(found, list) or not all(isinstance(p, str) for p in found):
            raise strict_json.StrictJSONError("not a list of paths")
    except (strict_json.StrictJSONError, OSError) as error:
        return frozenset(), [
            Notice(
                "config.present-unreadable",
                problem=f"troupe's record of the config files this clone had can't be read "
                f"({error}), so a config file that's missing was written again rather than read "
                "as removed.",
                fix="Nothing to do: troupe writes the record again. To remove something, delete "
                "its file again.",
                path=str(path),
            )
        ]
    return frozenset(found), []


def remember_present(troupe_dir: Path) -> None:
    """Record the config files there are now, as this clone's last sync leaves them."""
    from troupe.core.files import replace_file

    paths = sorted(on_disk(troupe_dir).files)
    target = troupe_dir / PRESENT
    target.parent.mkdir(parents=True, exist_ok=True)
    replace_file(target, strict_json.dumps(paths).encode("utf-8") + b"\n")
