"""Finding the theatre (perform-status-logs design D3).

The theatre is the nearest directory, from where a command starts upwards, that contains a
``.troupe`` directory. Nothing is created when there's none: a theatre exists because someone made
it, never because troupe guessed from a git work tree. This is how a surface on the person's
machine finds the theatre for its session; a run server addresses theatres by id instead. troupe
init makes one, refusing where one is already here or above (init-and-audition design D2).
"""

from pathlib import Path

from troupe.core.errors import TroupeError
from troupe.core.files import replace_file

THEATRE_DIR = ".troupe"


def existing_theatre(start: Path) -> Path | None:
    """The theatre's root: ``start`` or its nearest ancestor holding a ``.troupe`` directory, or
    None when there's none."""
    start = start.absolute()
    for directory in (start, *start.parents):
        if (directory / THEATRE_DIR).is_dir():
            return directory
    return None


def find_theatre(start: Path) -> Path:
    """The theatre's root: ``start`` or its nearest ancestor holding a ``.troupe`` directory."""
    found = existing_theatre(start)
    if found is not None:
        return found
    raise TroupeError(
        "theatre.not-found",
        problem=f"There's no troupe theatre here: no {THEATRE_DIR} directory in this directory "
        "or any directory above it.",
        fix="Run troupe inside a project that has a theatre, or make one at your project's root "
        "with troupe init (troupe init --audition adds a working example actor).",
        path=str(start.absolute()),
    )


def refuse_existing(start: Path) -> None:
    """Refuse to make a theatre at ``start`` when one is there or above it, or when a ``.troupe``
    that isn't a directory is in the way (spec: cli; init-and-audition design D2)."""
    start = start.absolute()
    in_the_way = start / THEATRE_DIR
    if in_the_way.exists() and not in_the_way.is_dir():
        raise TroupeError(
            "theatre.exists",
            problem=f"{in_the_way} is in the way: troupe keeps a theatre in a directory of that "
            "name, and this isn't a directory.",
            fix=f"Move or rename {in_the_way}, then run troupe init again.",
            path=str(in_the_way),
            details={"theatre": str(start), "directory": False},
        )
    found = existing_theatre(start)
    if found is not None:
        here = "here" if found == start else f"above this directory, at {found}"
        raise TroupeError(
            "theatre.exists",
            problem=f"There's already a troupe theatre {here}, so troupe init would make a second "
            "one.",
            fix="Use the theatre that's there: define an actor in it with troupe config set. To "
            "start again, remove its .troupe directory yourself.",
            path=str(found),
            details={"theatre": str(found), "directory": True},
        )


# The theatre's own git files (spec: config-files; config-model design D12). Whenever troupe writes
# into .troupe/, each of these files holds each of its patterns. A missing pattern is appended under
# a comment saying troupe added it and why; a line already there is never changed, moved or
# removed, so whatever a person wrote stays as they wrote it. A person who deletes one of troupe's
# lines gets it back on the next write, because troupe needs it.

GIT_FILES: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = (
    (
        ".gitignore",
        (
            ("local/", "troupe's local state: derived, per clone, never committed"),
            (".*.troupe~", "config files troupe is part-way through writing"),
        ),
    ),
    (
        ".gitattributes",
        (
            ("events/** -text", "event segments are byte-exact: never convert their line endings"),
            ("actors/** -text", "config files are byte-exact, so they match what troupe wrote"),
        ),
    ),
)
"""Each of the theatre's git files, and the patterns it must hold, each with why."""


def ensure_git_files(troupe_dir: Path) -> None:
    """Append to ``.troupe/.gitignore`` and ``.troupe/.gitattributes`` each pattern either is
    missing, creating them if they don't exist."""
    troupe_dir.mkdir(parents=True, exist_ok=True)
    for name, patterns in GIT_FILES:
        path = troupe_dir / name
        current = path.read_bytes() if path.exists() else b""
        newline = b"\r\n" if b"\r\n" in current else b"\n"
        lines = {line.rstrip(b"\r") for line in current.split(b"\n")}
        missing = [(line, why) for line, why in patterns if line.encode() not in lines]
        if not missing:
            continue
        added = b"".join(
            f"# Added by troupe: {why}.".encode() + newline + line.encode() + newline
            for line, why in missing
        )
        separator = newline if current and not current.endswith(b"\n") else b""
        replace_file(path, current + separator + added)
