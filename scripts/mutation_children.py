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

import contextlib
import importlib.util
import json
import os
import subprocess
import sys
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


MUTANT_MARK = "__mutmut_"
"""In every mutant's name (`troupe.core.x_f__mutmut_3`), and in no pass mutmut runs in its own
process (stats, the clean run, listing tests) or NO_MUTANT."""


CONFIG = Path(__file__).with_suffix(".json")
"""What mutation_run.py writes beside this file's copy: the per-mutant memory cap and where each
process records its peaks (#366, mutant-memory design D2). No file is no cap and no record."""

CONFIG_KEYS = {"mutant_memory_mb", "peaks"}


class PluginConfigError(Exception):
    """The plugin's config file is there but malformed: never read as no cap."""


def load_config(path: Path) -> dict[str, Any]:
    """The plugin's config, checked: `mutant_memory_mb` null or a positive whole number, and
    `peaks` null or a path. A missing file is the empty config, as before #366."""
    if not path.exists():
        return {"mutant_memory_mb": None, "peaks": None}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise PluginConfigError(f"{path} isn't JSON: {error}") from error
    if not isinstance(raw, dict):
        raise PluginConfigError(f"{path} isn't an object")
    for key in sorted(set(raw) - CONFIG_KEYS):
        raise PluginConfigError(
            f"{path} has the key {key!r}, which isn't one of {sorted(CONFIG_KEYS)}"
        )
    for key in sorted(CONFIG_KEYS - set(raw)):
        raise PluginConfigError(f"{path} has no {key!r}")
    cap = raw["mutant_memory_mb"]
    if cap is not None and (isinstance(cap, bool) or not isinstance(cap, int) or cap < 1):
        raise PluginConfigError(
            f"{path}: mutant_memory_mb is {cap!r}; it must be null or a positive whole number"
        )
    if raw["peaks"] is not None and not isinstance(raw["peaks"], str):
        raise PluginConfigError(f"{path}: peaks is {raw['peaks']!r}; it must be null or a path")
    return raw


STATUS = Path("/proc/self/status")
"""Where Linux gives a process its peak virtual (VmPeak) and resident (VmHWM) sizes."""


def record_peaks(peaks: Path, name: str, status: Path) -> None:
    """Append `<name> <VmPeak kB> <VmHWM kB>` to the peaks file, in one short O_APPEND write, so
    the processes mutmut runs at once don't interleave. With no status file (macOS) nothing."""
    try:
        fields = dict(
            line.split(":", 1)
            for line in status.read_text(encoding="utf-8").splitlines()
            if ":" in line
        )
    except OSError:
        return
    try:
        peak, resident = (int(fields[key].split()[0]) for key in ("VmPeak", "VmHWM"))
    except (KeyError, IndexError, ValueError):
        return
    fd = os.open(peaks, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(fd, f"{name} {peak} {resident}\n".encode())
    finally:
        os.close(fd)


def pytest_unconfigure(config: object) -> None:
    """When a process's tests end, it records its memory peaks, from which the per-mutant cap is
    set: mutmut's own passes as `mutmut`, a mutant's process by its mutant (#366, design D3). A
    process the kernel kills records nothing; one the cap stops with MemoryError does."""
    peaks = load_config(CONFIG)["peaks"]
    if peaks is None:
        return
    mutant = os.environ.get("MUTANT_UNDER_TEST", "")
    record_peaks(Path(peaks), mutant if MUTANT_MARK in mutant else "mutmut", STATUS)


def cap_address_space(megabytes: int) -> None:
    """RLIMIT_AS for this process and what it starts: a runaway mutant's allocation then fails
    here (MemoryError, or the process dies) instead of running the run's cgroup out (#366, D1).

    Nothing on Windows, where no mutation run happens. Narrowing on sys.platform is what lets
    mypy check this file as Windows sees it, which troupe's Windows legs do (#369)."""
    if sys.platform == "win32":
        return
    import resource

    limit = megabytes * 1024 * 1024
    _, hard = resource.getrlimit(resource.RLIMIT_AS)
    if hard != resource.RLIM_INFINITY:
        limit = min(limit, hard)
    resource.setrlimit(resource.RLIMIT_AS, (limit, limit))


def pytest_configure(config: object) -> None:
    """Loaded as a plugin (`-p mutation_children`): only then are children's environments set.

    A mutant's test process (mutmut forks one per mutant) also starts a session of its own, so a
    mutant that signals its own process group, as one of troupe's `os.killpg` can, ends only its
    own tests: mutmut counts it as crashed and goes on. A GitHub step shares the runner agent's
    process group, which such a mutant would otherwise kill (#341; mutation-session design D1).

    A mutant's test process also runs under the settings' per-mutant memory cap, when there is
    one (#366). mutmut's own process, where its stats and clean passes run, never does: every
    mutant's process is forked from it.
    """
    subprocess.Popen.__init__ = _popen_init  # type: ignore[method-assign]
    if MUTANT_MARK in os.environ.get("MUTANT_UNDER_TEST", "") and hasattr(os, "setsid"):
        # A process that already leads its group can't start a session, and a kill of its own
        # group then reaches only itself and what it started: contained either way.
        with contextlib.suppress(PermissionError):
            os.setsid()
    settings = load_config(CONFIG)
    if MUTANT_MARK in os.environ.get("MUTANT_UNDER_TEST", "") and settings["mutant_memory_mb"]:
        cap_address_space(settings["mutant_memory_mb"])
