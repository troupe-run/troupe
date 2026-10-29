# /// script
# dependencies = []
# ///
"""Install troupe the documented way, from a commit, and run it (spec: installation).

Usage: uv run scripts/install_check.py [--ref REF] [--python VERSION]

Runs the install command the README and the user docs give, with this checkout as the repository
and REF (default HEAD) as the ref, into a tool directory of its own (install-with-uv design D4).
Then it runs the installed `troupe --version`, and a scripted performance in a new theatre outside
the checkout, as "Your first performance" does. Nothing is installed into your own uv tool directory
or onto your path, and everything is removed afterwards. CI runs it against the commit under test
on every platform and Python (design D5).

The header above makes `uv run` treat this as a standalone script, so it starts without syncing
the default .venv. Standard library only, like check.py.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPOSITORY = "https://github.com/troupe-run/troupe"
"""Where the documented command installs from."""
SUBDIRECTORY = "packages/troupe-run"
"""The bundle (design D1), which installs troupe with everything it bundles."""
TEMPLATE = 'uv tool install "git+{repository}@{ref}#subdirectory=' + SUBDIRECTORY + '"'
"""The install command, the one form the README, the user docs and this check use (design D3)."""
DOCUMENTED_REFS = ("main", "<commit>")
"""The refs the docs may name: the latest main, or a placeholder for a commit of your choosing."""

INSTALL_TIMEOUT = 600.0
"""Seconds the install may take: the first one resolves and builds every package."""
COMMAND_TIMEOUT = 120.0
"""Seconds each other command may take, the scripted performance included."""

SCRIPT = {
    "script": {
        "steps": [
            {
                "event": {
                    "type": "init",
                    "runner": {"name": "scripted", "version": "0.1.0"},
                    "tools": ["Write"],
                }
            },
            {"writeFile": {"path": "out/hello.txt", "content": "hello\n"}},
            {"event": {"type": "result", "status": "ok", "message": "wrote out/hello.txt"}},
        ]
    }
}
"""The scripted runner's options from "Your first performance": write one file."""
_SUCCEEDED = re.compile(r"^run \S+ succeeded$", re.MULTILINE)
_COMMIT = re.compile(r"[0-9a-f]{40}([0-9a-f]{24})?")


class InstallCheckError(Exception):
    """A step failed. The message names the step, the command and what it printed."""


def command(repository: str, ref: str) -> str:
    """The documented install command, for a repository URL and a ref."""
    return TEMPLATE.format(repository=repository, ref=ref)


def install_arguments(repository: str, ref: str, python: str | None) -> list[str]:
    """The arguments `uv` runs for the documented command, with `--python` when one is given."""
    url = f"git+{repository}@{ref}#subdirectory={SUBDIRECTORY}"
    return ["tool", "install", url, *(["--python", python] if python else [])]


def repository_url(root: Path) -> str:
    """The checkout as a repository uv can clone: a file URL, so any of its commits installs."""
    return root.resolve().as_uri()


@dataclass(frozen=True)
class Tools:
    """A tool directory of the check's own, and the variables that point uv at it."""

    directory: Path
    bin: Path

    def environment(self, base: Mapping[str, str]) -> dict[str, str]:
        return {**base, "UV_TOOL_DIR": str(self.directory), "UV_TOOL_BIN_DIR": str(self.bin)}


@contextmanager
def scratch() -> Iterator[Path]:
    """A temporary directory, removed afterwards, whatever happened in it."""
    with tempfile.TemporaryDirectory(prefix="troupe-install-check-") as name:
        yield Path(name)


def run(step: str, argv: Sequence[str], cwd: Path, env: Mapping[str, str], timeout: float) -> str:
    """Run one step's command, returning its standard output. Refused, naming it, if it fails."""
    shown = " ".join(argv)
    try:
        done = subprocess.run(
            list(argv),
            cwd=cwd,
            env=dict(env),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise InstallCheckError(f"{step}: `{shown}` didn't finish within {timeout:g}s.") from error
    except OSError as error:
        raise InstallCheckError(f"{step}: `{shown}` couldn't start: {error}.") from error
    if done.returncode != 0:
        raise InstallCheckError(
            f"{step}: `{shown}` exited {done.returncode}.\n"
            f"standard output:\n{done.stdout}\nstandard error:\n{done.stderr}"
        )
    return done.stdout


def resolve(root: Path, ref: str) -> str:
    """The commit `ref` names in the checkout. Refused, naming it, when it names none."""
    git = _program("git")
    done = subprocess.run(
        [git, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=COMMAND_TIMEOUT,
        check=False,
    )
    sha = done.stdout.strip()
    if done.returncode != 0 or not _COMMIT.fullmatch(sha):
        raise InstallCheckError(
            f"--ref {ref!r} isn't a commit in {root}: name a commit, a branch or a tag "
            "that's in this checkout."
        )
    return sha


def core_version(root: Path, sha: str) -> str:
    """The version core's pyproject.toml declares at a commit."""
    shown = run(
        "read core's version",
        [_program("git"), "show", f"{sha}:packages/troupe/pyproject.toml"],
        root,
        os.environ,
        COMMAND_TIMEOUT,
    )
    version: str = tomllib.loads(shown)["project"]["version"]
    return version


def _program(name: str, path: str | None = None) -> str:
    found = shutil.which(name, path=path)
    if found is None:
        where = path if path is not None else "PATH"
        raise InstallCheckError(f"{name} isn't on {where}: install it, or run this with `uv run`.")
    return found


def check(root: Path, ref: str, python: str | None) -> str:
    """Install `ref` the documented way and perform with it. Returns the run's line."""
    sha = resolve(root, ref)
    version = core_version(root, sha)
    with scratch() as place:
        tools = Tools(directory=place / "tools", bin=place / "bin")
        env = tools.environment(os.environ)
        run(
            "install",
            [_program("uv"), *install_arguments(repository_url(root), sha, python)],
            place,
            env,
            INSTALL_TIMEOUT,
        )
        troupe = _program("troupe", path=str(tools.bin))
        shown = run("troupe --version", [troupe, "--version"], place, env, COMMAND_TIMEOUT)
        if f"troupe {version} " not in shown:
            raise InstallCheckError(
                f"troupe --version: printed {shown.strip()!r}, not troupe {version}, the version "
                f"core declares at {sha}."
            )
        return _perform(place / "theatre", troupe, env)


def _perform(theatre: Path, troupe: str, env: dict[str, str]) -> str:
    """The "Your first performance" path, in a new theatre: a scripted actor writes one file."""
    git = _program("git")
    # Local settings only: the person's signing, hooks and identity stay out of it.
    local = ["-c", "commit.gpgsign=false", "-c", "core.hooksPath="]
    theatre.mkdir()
    (theatre / ".troupe").mkdir()
    (theatre / "hello.json").write_text(json.dumps(SCRIPT), encoding="utf-8")
    steps: list[tuple[str, list[str]]] = [
        ("make the theatre's repository", [git, "init", "--quiet"]),
        ("set its identity", [git, "config", "user.email", "install-check@troupe.run"]),
        ("set its identity", [git, "config", "user.name", "install check"]),
        (
            "define the actor",
            [
                troupe,
                "config",
                "set",
                "actors.tester.runner=scripted",
                "actors.tester.options=@hello.json",
                'actors.tester.expect=["out/hello.txt"]',
            ],
        ),
        ("commit", [git, *local, "add", "-A"]),
        ("commit", [git, *local, "commit", "--quiet", "-m", "Add the tester actor"]),
    ]
    for step, argv in steps:
        run(step, argv, theatre, env, COMMAND_TIMEOUT)
    performing = {**env, "TROUPE_POLICY_ALLOW_UNENFORCED_LOCAL_STAGE": "true"}
    perform = [troupe, "perform", "tester"]
    shown = run("perform", perform, theatre, performing, COMMAND_TIMEOUT)
    succeeded = _SUCCEEDED.search(shown)
    if succeeded is None:
        raise InstallCheckError(
            f"perform: `{' '.join(perform)}` printed {shown!r}, not run <id> succeeded."
        )
    return succeeded.group(0)


def main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="uv run scripts/install_check.py",
        description="Install troupe the documented way from a commit of this checkout, and run it.",
    )
    parser.add_argument("--ref", default="HEAD", help="the commit to install (default: HEAD)")
    parser.add_argument("--python", help="the Python to install it on (default: uv's choice)")
    arguments = parser.parse_args(argv)
    try:
        line = check(ROOT, arguments.ref, arguments.python)
    except InstallCheckError as error:
        print(f"install check: {error}", file=sys.stderr)
        return 1
    print(f"install check: installed and performed ({line})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
