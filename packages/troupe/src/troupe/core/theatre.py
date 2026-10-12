"""Finding the theatre (perform-status-logs design D3).

The theatre is the nearest directory, from where a command starts upwards, that contains a
``.troupe`` directory. Nothing is created when there's none: a theatre exists because someone made
it, never because troupe guessed from a git work tree. This is how a surface on the person's
machine finds the theatre for its session; a run server addresses theatres by id instead.
"""

from pathlib import Path

from troupe.core.errors import TroupeError

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
