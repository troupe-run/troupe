"""A pytest plugin that drops hypothesis's per-example deadline for every test path (#100).

Loaded for every test path through ``addopts`` in pyproject.toml. Hypothesis's own ``default``
profile, which local runs, the commit hook and the flake hunt use, fails an example that takes over
200 ms. Its ``ci`` profile, which GitHub Actions gets because it sets ``CI``, has no deadline. Tests
that do real I/O (an fsync, a temporary directory, a child process) can take longer than that on a
loaded machine: on Windows, under the flake hunt, one append example took 564 ms and failed. So the
deadline is a flake source locally that CI never sees.

This re-registers ``default`` with the deadline off and everything else hypothesis's own. Changing
the active profile takes effect at once, and ``ci`` keeps its fixed seeds and no database. It is
the one place this is decided, so a new I/O-bound hypothesis test can't forget it.
"""

from hypothesis import settings

settings.register_profile("default", parent=settings.get_profile("default"), deadline=None)
