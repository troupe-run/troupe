# /// script
# dependencies = []
# ///
"""Run a command on any supported Python, in that version's own environment (spec: python-support).

Usage: uv run scripts/on.py VERSION COMMAND...

For example, `uv run scripts/on.py 3.13 scripts/check.py`. Each version gets its own environment
in .venvs/VERSION, so switching versions rebuilds nothing, and two terminals on different versions
don't clash. A version outside the root's requires-python is refused before uv runs
(python-version-bounds design D5).

The header above makes `uv run` treat this as a standalone script, so it starts without syncing
the default .venv. Standard library only, like check.py.
"""

import os
import re
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

import python_versions

ROOT = Path(__file__).resolve().parent.parent
ENVIRONMENTS = ".venvs"
USAGE = "usage: uv run scripts/on.py VERSION COMMAND..."
EXAMPLE = "`uv run scripts/on.py {version} scripts/check.py`"
HELP = (
    "Runs COMMAND with uv on Python VERSION, in its own environment in .venvs/VERSION.\n"
    "Delete .venvs/ at any time; each environment is rebuilt on its next use."
)
_VERSION = re.compile(r"3\.(0|[1-9][0-9]*)")

Runner = Callable[[list[str], Path, dict[str, str]], int]


def _subprocess(command: list[str], cwd: Path, env: dict[str, str]) -> int:
    return subprocess.run(command, cwd=cwd, env=env, check=False).returncode


def _listed(versions: Sequence[str]) -> str:
    return versions[0] if len(versions) == 1 else f"{', '.join(versions[:-1])} and {versions[-1]}"


def command(version: str, arguments: Sequence[str]) -> tuple[list[str], dict[str, str]]:
    """The uv command that runs arguments on version, and the environment to run it in."""
    env = {key: value for key, value in os.environ.items() if key != "VIRTUAL_ENV"}
    env["UV_PROJECT_ENVIRONMENT"] = str(ROOT / ENVIRONMENTS / version)
    uv = os.environ.get("UV", "uv")
    return [uv, "run", "--python", version, "--", *arguments], env


def main(argv: Sequence[str], run: Runner = _subprocess) -> int:
    supported = python_versions.supported(ROOT)
    if argv and argv[0] in ("-h", "--help"):
        print(f"{USAGE}\n\n{HELP}\nSupported versions: {', '.join(supported)}.")
        return 0
    if not argv:
        print(f"{USAGE}\nFor example, {EXAMPLE.format(version=supported[-1])}.", file=sys.stderr)
        return 2
    version, arguments = argv[0], list(argv[1:])
    if _VERSION.fullmatch(version) is None:
        print(
            f"on: {version!r} isn't a Python version: give a minor version like 3.13, for example "
            f"{EXAMPLE.format(version='3.13')}.",
            file=sys.stderr,
        )
        return 2
    if version not in supported:
        print(
            f"on: Python {version} isn't supported: requires-python "
            f'"{python_versions.bound(ROOT)}" in {python_versions.PYPROJECT} supports '
            f"{_listed(supported)}. Run on one of those, or widen the bound and CI's matrix "
            "together.",
            file=sys.stderr,
        )
        return 2
    if not arguments:
        print(
            f"on: name a command to run on {version}, for example "
            f"{EXAMPLE.format(version=version)}.",
            file=sys.stderr,
        )
        return 2
    uv, env = command(version, arguments)
    return run(uv, ROOT, env)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
