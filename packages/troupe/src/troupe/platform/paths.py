"""How paths are shown to people: absolute, with the home directory abbreviated to ``~``.

Never ``.`` and never relative to the working directory, so a path in a message means the same thing
wherever it is read. The separator after ``~`` is the platform's own (``~/x`` on POSIX, ``~\\x`` on
Windows). Matching the home directory ignores case on Windows and macOS, whose file systems are
case-insensitive by default.
"""

import os
import sys
from pathlib import Path, PurePath

_CASE_INSENSITIVE = sys.platform in ("win32", "darwin")


def _key(path: PurePath) -> tuple[str, ...]:
    parts = path.parts
    return tuple(part.casefold() for part in parts) if _CASE_INSENSITIVE else parts


def friendly(path: str | os.PathLike[str], *, home: str | os.PathLike[str] | None = None) -> str:
    """Display form of ``path``: absolute, with ``home`` (default: the user's) shown as ``~``."""
    absolute = Path(os.path.normpath(Path(path).absolute()))
    home_path = Path(os.path.normpath(Path.home() if home is None else Path(home).absolute()))
    home_key = _key(home_path)
    path_key = _key(absolute)
    if path_key[: len(home_key)] == home_key:
        rest = absolute.parts[len(home_key) :]
        return "~" if not rest else "~" + os.sep + os.sep.join(rest)
    return str(absolute)
