"""Finding the theatre (perform-status-logs design D3).

The theatre is the nearest directory, from where a command starts upwards, that contains a
``.troupe`` directory. Nothing is created when there's none: a theatre exists because someone made
it, never because troupe guessed from a git work tree. This is how a surface on the person's
machine finds the theatre for its session; a run server addresses theatres by id instead.
"""

from pathlib import Path

from troupe.core.errors import TroupeError
from troupe.core.files import replace_file

THEATRE_DIR = ".troupe"


def find_theatre(start: Path) -> Path:
    """The theatre's root: ``start`` or its nearest ancestor holding a ``.troupe`` directory."""
    start = start.absolute()
    for directory in (start, *start.parents):
        if (directory / THEATRE_DIR).is_dir():
            return directory
    raise TroupeError(
        "theatre.not-found",
        problem=f"There's no troupe theatre here: no {THEATRE_DIR} directory in this directory "
        "or any directory above it.",
        fix=f"Run troupe inside a project that has a {THEATRE_DIR} directory, or create one at "
        f"your project's root (mkdir {THEATRE_DIR}).",
        path=str(start),
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
