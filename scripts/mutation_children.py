"""A pytest plugin for mutation runs only: a child process never runs mutmut's stats hook
(lint-mutation design D3).

mutmut 3 records which tests reach which functions by a hook in each mutated function, which reads
mutmut's setup.cfg from the working directory. A test that runs a script in a subprocess, as the
guard's tests do, from a temporary repository, inherits MUTANT_UNDER_TEST=stats, and the hook
fails there. So while mutmut collects its stats, a child gets a value naming no mutant, and runs
the original code. While mutmut tests a mutant, a child inherits that mutant's name, so a test
that runs the mutated script still kills it. mutation_run.py copies this file into mutmut's
working directory and loads it with `-p`; nothing else loads it.

What a child runs isn't seen by mutmut's stats: a function reached only through a subprocess has
no tests as far as mutmut knows, and its mutants count as not covered.
"""

import importlib.util
import os
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any

STATS = "stats"
NO_MUTANT = "none.none"
"""A mutant in no module: every hook calls the original function (mutmut 3.8.1's trampoline)."""

_original_init = subprocess.Popen.__init__


def child_env(env: Mapping[str, str] | None, mutmut_path: str) -> dict[str, str] | None:
    """The environment a child gets: mutmut importable, and never the stats hook.

    A mutated module imports mutmut's hooks, and a test may run it with another interpreter, as
    the guard's git hooks do (`uv run --no-project`), so mutmut's installation joins PYTHONPATH.
    A child of a run with no mutant at all is left alone.
    """
    current = env if env is not None else os.environ
    mutant = current.get("MUTANT_UNDER_TEST")
    if mutant is None:
        return None if env is None else dict(env)
    paths = [path for path in current.get("PYTHONPATH", "").split(os.pathsep) if path]
    return {
        **current,
        "MUTANT_UNDER_TEST": NO_MUTANT if mutant == STATS else mutant,
        "PYTHONPATH": os.pathsep.join([*paths, mutmut_path] if mutmut_path not in paths else paths),
    }


def mutmut_path() -> str:
    """The directory mutmut is installed in, so a child can import it."""
    found = importlib.util.find_spec("mutmut")
    if found is None or found.origin is None:
        raise RuntimeError("mutation_children runs under mutmut, which isn't importable here")
    return str(Path(found.origin).resolve().parent.parent)


def _popen_init(self: subprocess.Popen[Any], *args: Any, **kwargs: Any) -> None:  # noqa: ANN401
    kwargs["env"] = child_env(kwargs.get("env"), mutmut_path())
    _original_init(self, *args, **kwargs)


def pytest_configure(config: object) -> None:
    """Loaded as a plugin (`-p mutation_children`): only then are children's environments set."""
    subprocess.Popen.__init__ = _popen_init  # type: ignore[method-assign]
