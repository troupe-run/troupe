"""A pytest plugin that sets hypothesis's ``default`` profile for every test path (#100, #537).

Loaded for every test path through ``addopts`` in pyproject.toml, so it runs whichever directory
pytest is started from. Hypothesis's own ``default`` profile, which local runs, the commit hook and
the flake hunt use, differs from what the repository needs in two ways.

It fails an example that takes over 200 ms. Its ``ci`` profile, which GitHub Actions gets because it
sets ``CI``, has no deadline. Tests that do real I/O (an fsync, a temporary directory, a child
process) can take longer than that on a loaded machine: on Windows, under the flake hunt, one append
example took 564 ms and failed. So the deadline is a flake source locally that CI never sees.

It keeps its example database in ``.hypothesis/`` under the current directory. So a failure found
by pytest started from ``packages/troupe`` was saved there, and ``scripts/check.py``, which runs
from the root, never replayed it: #532's bug passed the full check that way. Here every run shares
the root's ``.hypothesis/examples``. ``HYPOTHESIS_STORAGE_DIRECTORY``, when set, still decides
instead: the flake hunt gives each round a private database that way (one-hypothesis-database
design D1, D2).

This re-registers ``default`` with the deadline off, that database, and everything else
hypothesis's own. Changing the active profile takes effect at once, and ``ci`` keeps its fixed seeds
and no database. It is the one place this is decided, so a new test can't forget it.
"""

import os
from collections.abc import Mapping
from pathlib import Path

from hypothesis import settings
from hypothesis.database import DirectoryBasedExampleDatabase

ROOT = Path(__file__).resolve().parents[3]
"""The repository root: this file is packages/troupe/tests/hypothesis_profiles.py."""

EXAMPLES = ROOT / ".hypothesis" / "examples"
"""The one example database every run in this checkout shares."""


def shared_database(environ: Mapping[str, str]) -> DirectoryBasedExampleDatabase | None:
    """The root's database, or None to leave hypothesis's own, which an environment storage
    directory then decides (design D2). Hypothesis reads an empty value as unset, and so does
    this."""
    if environ.get("HYPOTHESIS_STORAGE_DIRECTORY"):
        return None
    return DirectoryBasedExampleDatabase(EXAMPLES)


_database = shared_database(os.environ)
if _database is None:
    settings.register_profile("default", parent=settings.get_profile("default"), deadline=None)
else:
    settings.register_profile(
        "default", parent=settings.get_profile("default"), deadline=None, database=_database
    )
