"""Interim choices that config replaces (perform-status-logs design D4).

Until actors are configured, a perform request names its runner. This table is the only place a
runner's name becomes a command line, so no request can carry a program to run. When config lands,
the actor's config names its runner, resolved to a plugin named and pinned there (#38), and this
module is deleted.
"""

import sys
from collections.abc import Sequence

from troupe.core.errors import TroupeError

RUNNERS: dict[str, tuple[str, ...]] = {
    "scripted": (sys.executable, "-m", "troupe_runner_scripted"),
}
"""Each runner perform knows, by name, and the command line that starts it."""


def runner_command(name: str) -> Sequence[str]:
    """The command line that starts the runner named ``name``."""
    if name not in RUNNERS:
        known = ", ".join(sorted(RUNNERS))
        raise TroupeError(
            "runner.unknown",
            problem=f"troupe doesn't know a runner named {name!r} (it knows: {known}).",
            fix=f"Use one of: {known}. Until actors are configured, these are the only runners "
            "perform can start.",
            details={"runner": name, "known": sorted(RUNNERS)},
        )
    return RUNNERS[name]
