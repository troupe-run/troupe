"""Renaming an actor or runtime: what a rename may do, and the files it moves (spec: config, "Only a
whole actor or runtime can be renamed", "A rename needs its source and refuses an existing
target", "A built-in runtime's name is never renamed to or from"; config-mv design D5, D7).
"""

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from troupe.core import defaults
from troupe.core.config.changes import RENAMED_FROM, Rename, get, is_rename
from troupe.core.config.kinds import ACTORS, KINDS, RUNTIMES, actor_files, runtime_file
from troupe.core.config_paths import shown
from troupe.core.errors import TroupeError

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
    whole actor or runtime to a free name of its kind, or that names a built-in runtime."""
    new, old = tuple(path), tuple(source)
    details = {"path": list(new), "from": list(old)}
    if len(new) != 2 or len(old) != 2 or old[0] not in KINDS or new[0] not in KINDS:
        raise TroupeError(
            "config.move-not-entity",
            problem=f"troupe config mv renames a whole actor or runtime, and {shown(old)} to "
            f"{shown(new)} isn't one: only actors.<name> and runtimes.<name> can be renamed.",
            fix="Name the actor or runtime itself, such as troupe config mv actors.tester "
            "actors.qa; to change a value, use troupe config set.",
            details={**details, "rule": "only a whole actor or runtime can be renamed"},
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
    return "an actor" if kind == ACTORS else "a runtime"


def files_of(kind: str, name: str) -> tuple[str, ...]:
    """The config files an entity has, relative to .troupe/."""
    return actor_files(name) if kind == ACTORS else (runtime_file(name),)


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
    the old files is there, and the new main file (an actor's .yaml, a runtime's file) is."""
    if len(path) != 2 or len(source) != 2 or path[0] not in KINDS or source[0] != path[0]:
        return False
    old = files_of(source[0], source[1])
    new = files_of(path[0], path[1])
    return not any((troupe_dir / f).exists() for f in old) and (troupe_dir / new[0]).is_file()
