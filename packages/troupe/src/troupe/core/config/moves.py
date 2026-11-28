"""Renaming an actor, runtime or flow: what a rename may do, the files it moves, and the hand moves
a sweep pairs (spec: config-renames, "Only a whole actor or runtime can be renamed", "A rename
needs its source and refuses an existing target", "A built-in runtime's name is never renamed to
or from"; config-hand-edits, "A hand move with the same values is a rename", "An ambiguous hand
move is refused"; config-mv design D5, D6, D7)."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from troupe.core import defaults
from troupe.core.config.changes import RENAMED_FROM, Rename, get, is_rename, value_hash
from troupe.core.config.kinds import (
    ACTORS,
    CHARACTER,
    FLOWS,
    KINDS,
    RUNTIMES,
    actor_files,
    flow_file,
    runtime_file,
)
from troupe.core.config_paths import shown
from troupe.core.errors import TroupeError
from troupe.core.notices import Notice
from troupe.core.theatre import THEATRE_DIR

if TYPE_CHECKING:
    from troupe.core.config.reading import FileValues

Operation = tuple[Sequence[str], object]


def renames(operations: Sequence[Operation]) -> list[tuple[tuple[str, ...], tuple[str, ...]]]:
    """Each rename in ``operations``: its new path and its old one."""
    return [
        (tuple(path), tuple(value.source))
        for path, value in operations
        if isinstance(value, Rename)
    ]


def refuse_move(config: Mapping[str, Any], path: Sequence[str], source: Sequence[str]) -> None:
    """Refuse, recording nothing, a rename of ``source`` to ``path`` in ``config`` that isn't a
    whole actor, runtime or flow to a free name of its kind, or that names a built-in runtime."""
    new, old = tuple(path), tuple(source)
    details = {"path": list(new), "from": list(old)}
    if len(new) != 2 or len(old) != 2 or old[0] not in KINDS or new[0] not in KINDS:
        raise TroupeError(
            "config.move-not-entity",
            problem=f"troupe config mv renames a whole actor, runtime or flow, and {shown(old)} to "
            f"{shown(new)} isn't one: only actors.<name>, runtimes.<name> and flows.<name> can be "
            "renamed.",
            fix="Name the actor, runtime or flow itself, such as troupe config mv actors.tester "
            "actors.qa; to change a value, use troupe config set.",
            details={**details, "rule": "only a whole actor, runtime or flow can be renamed"},
        )
    if old[0] != new[0]:
        raise TroupeError(
            "config.move-not-entity",
            problem=f"{shown(old)} is {_a(old[0])} and {shown(new)} would be {_a(new[0])}: a "
            "rename keeps its kind.",
            fix=f"Rename it to {old[0]}.<new name>.",
            details={**details, "rule": "a rename keeps its kind"},
        )
    if old[0] == RUNTIMES:
        for name in (old[1], new[1]):
            if name in defaults.RUNTIMES:
                raise TroupeError(
                    "config.move-built-in",
                    problem=f"{name} is one of troupe's built-in runtimes: a runtime in config "
                    "with its name holds overrides of the built-in, not a runtime of its own, so "
                    "it's never renamed to or from.",
                    fix="To use another name, set the runtime's values under it with troupe "
                    "config set, and point actors at it.",
                    details={**details, "runtime": name},
                )
    if not isinstance(get(config, old), Mapping):
        raise TroupeError(
            "config.move-source-missing",
            problem=f"Config has no {shown(old)} to rename.",
            fix="Check the name with troupe config get " + old[0] + ".",
            details=details,
        )
    if get(config, new) is not None:
        raise TroupeError(
            "config.move-target-exists",
            problem=f"Config already has {shown(new)}, so {shown(old)} can't be renamed to it.",
            fix=f"Rename it to a name config doesn't hold, or first remove {shown(new)} (troupe "
            f"config unset {shown(new)}).",
            details=details,
        )


def _a(kind: str) -> str:
    return {ACTORS: "an actor", FLOWS: "a flow"}.get(kind, "a runtime")


def files_of(kind: str, name: str) -> tuple[str, ...]:
    """The config files an entity has, relative to .troupe/."""
    if kind == ACTORS:
        return actor_files(name)
    return (flow_file(name),) if kind == FLOWS else (runtime_file(name),)


def moved_files(entries: Sequence[Mapping[str, Any]]) -> dict[str, str]:
    """For each rename among ``entries``, each new file's path and the old file it moves from
    (design D7)."""
    found: dict[str, str] = {}
    for entry in entries:
        if not is_rename(entry):
            continue
        kind, new = entry["path"]
        _, old = entry[RENAMED_FROM]
        found.update(zip(files_of(kind, new), files_of(kind, old), strict=True))
    return found


def already_moved(troupe_dir: Path, path: Sequence[str], source: Sequence[str]) -> bool:
    """Whether a person has already moved ``source``'s files to ``path``'s names by hand: none of
    the old files is there, and the new main file (an actor's .yaml, a runtime's or a flow's
    file) is."""
    if len(path) != 2 or len(source) != 2 or path[0] not in KINDS or source[0] != path[0]:
        return False
    old = files_of(source[0], source[1])
    new = files_of(path[0], path[1])
    return not any((troupe_dir / f).exists() for f in old) and (troupe_dir / new[0]).is_file()


# Hand moves (config-mv design D6)


@dataclass(frozen=True)
class Pair:
    """A hand move the sweep read: an entity's files gone, and another's of the same kind arrived
    with the same values."""

    kind: str
    old: str
    new: str
    gone: tuple[str, ...]
    """The old entity's files, gone since this clone's last sync."""
    arrived: tuple["FileValues", ...]
    """The new entity's files, as read."""

    @property
    def main(self) -> str:
        """The new entity's main file: an actor's .yaml, a runtime's file."""
        return files_of(self.kind, self.new)[0]


def _whole(reads: Sequence["FileValues"]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for read in reads:
        values.update(read.values)
    return values


def pair_moves(
    config: Mapping[str, Any], reads: Sequence["FileValues"], removed: Sequence[str]
) -> tuple[list[Pair], list[Notice]]:
    """The hand moves among a sweep's ``reads`` and ``removed`` files: each entity whose files are
    all gone, paired with a new entity of its kind (one config doesn't hold) holding equal values.
    Refuses an ambiguous pairing with ``config.move-ambiguous``; a pair naming a built-in runtime,
    and entities left unpaired, are named in ``config.move-not-detected`` notices."""
    gone = _gone(config, removed)
    arrived = _arrived(config, reads)
    by_hash: dict[tuple[str, str], tuple[list[tuple[str, str]], list[tuple[str, str]]]] = {}
    for key, values in gone.items():
        by_hash.setdefault((key[0], value_hash(values)), ([], []))[0].append(key)
    for key, files in arrived.items():
        by_hash.setdefault((key[0], value_hash(_whole(files))), ([], []))[1].append(key)
    pairs: list[Pair] = []
    notices: list[Notice] = []
    told: set[tuple[str, str]] = set()
    for olds, news in by_hash.values():
        if not olds or not news:
            continue
        if len(olds) > 1 or len(news) > 1:
            raise _ambiguous(olds, news, gone, arrived)
        old, new = olds[0], news[0]
        if old[0] == RUNTIMES and (old[1] in defaults.RUNTIMES or new[1] in defaults.RUNTIMES):
            notices.append(_not_detected([old], [new], "built-in"))
            told.update((old, new))
            continue
        old_files = tuple(f for f in files_of(*old) if f in removed)
        pairs.append(Pair(old[0], old[1], new[1], old_files, tuple(arrived[new])))
    paired_old = {(p.kind, p.old) for p in pairs} | told
    paired_new = {(p.kind, p.new) for p in pairs} | told
    for kind in KINDS:
        left_old = sorted(k for k in gone if k[0] == kind and k not in paired_old)
        left_new = sorted(k for k in arrived if k[0] == kind and k not in paired_new)
        if left_old and left_new:
            notices.append(_not_detected(left_old, left_new, "values differ"))
    return pairs, notices


def _gone(config: Mapping[str, Any], removed: Sequence[str]) -> dict[tuple[str, str], Any]:
    """Each entity config holds whose files are all among ``removed``, with its values."""
    from troupe.core.config.reading import owner

    found: dict[tuple[str, str], Any] = {}
    for path in removed:
        located = owner(path)
        if located is None:
            continue
        key = located[0]
        group = get(config, key)
        if not isinstance(group, Mapping) or key in found:
            continue
        needed = list(files_of(*key))
        if key[0] == ACTORS and CHARACTER not in group:
            needed = needed[:1]
        if all(f in removed for f in needed):
            found[key] = dict(group)
    return found


def _arrived(
    config: Mapping[str, Any], reads: Sequence["FileValues"]
) -> dict[tuple[str, str], list["FileValues"]]:
    """Each entity config doesn't hold whose main file was read, with the files read for it."""
    found: dict[tuple[str, str], list[FileValues]] = {}
    for read in reads:
        if get(config, read.group) is None:
            found.setdefault(read.group, []).append(read)
    return {key: files for key, files in found.items() if any(f.owns == "fields" for f in files)}


def _ambiguous(
    olds: Sequence[tuple[str, str]],
    news: Sequence[tuple[str, str]],
    gone: Mapping[tuple[str, str], Any],
    arrived: Mapping[tuple[str, str], Sequence["FileValues"]],
) -> TroupeError:
    files = sorted(
        [f"{THEATRE_DIR}/{files_of(*key)[0]}" for key in olds]
        + [f"{THEATRE_DIR}/{r.path}" for key in news for r in arrived[key] if r.owns == "fields"]
    )
    old_names = ", ".join(shown(key) for key in sorted(olds))
    new_names = ", ".join(shown(key) for key in sorted(news))
    example = f"troupe config mv {shown(sorted(olds)[0])} {shown(sorted(news)[0])}"
    return TroupeError(
        "config.move-ambiguous",
        problem=f"Files were moved by hand, and troupe can't tell which is which: {old_names} "
        f"went and {new_names} arrived, all holding the same values ({', '.join(files)}). "
        "Nothing was recorded.",
        fix=f"Name each rename you meant with troupe config mv, such as {example}: run on files "
        "already moved, it records the rename and writes nothing.",
        details={"files": files},
    )


def _not_detected(
    olds: Sequence[tuple[str, str]], news: Sequence[tuple[str, str]], reason: str
) -> Notice:
    removed = [shown(key) for key in olds]
    added = [shown(key) for key in news]
    why = (
        "a built-in runtime's name is never renamed to or from"
        if reason == "built-in"
        else "their values differ, so it can't be told from deleting one and writing another"
    )
    return Notice(
        "config.move-not-detected",
        problem=f"troupe read {', '.join(removed)} going and {', '.join(added)} arriving as a "
        f"removal and an addition, not a rename: {why}.",
        fix="To keep the history, put the files back, then rename with troupe config mv (run on "
        "files already moved, it records the rename), and edit after.",
        details={"removed": removed, "added": added, "reason": reason},
    )
