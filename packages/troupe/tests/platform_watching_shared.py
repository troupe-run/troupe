"""What test_platform_watching.py and test_platform_watching_integration.py share."""

from pathlib import Path

from storetesting import SETTLE
from troupe.platform.watching import DirectoryWatch, watch


def drain(watched: DirectoryWatch, quiet: float = 0.2) -> None:
    """Wait until ``watched`` has reported nothing for ``quiet`` seconds. One change can be
    reported as more than one wake."""
    while watched.wait(quiet):
        pass


def settled(directory: Path) -> DirectoryWatch:
    """A watch on ``directory`` with its spurious first wakes used up."""
    watched = watch(directory)
    drain(watched, SETTLE)
    return watched
