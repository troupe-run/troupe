# /// script
# dependencies = []
# ///
"""Install troupe the documented way, from a commit or a tag, and run it (spec: installation).

Usage: uv run scripts/install_check.py [--ref REF] [--python VERSION] [--hosted]

Runs the install command the README and the user docs give, with this checkout as the repository
and REF (default HEAD) as the ref, into a tool directory of its own (install-with-uv design D4).
With --hosted it installs from GitHub instead, with REF exactly as given, as someone following
the docs would: the release install check runs it against each published troupe-run-v<version>
tag (install-from-tag design D4, D5). REF is still resolved in this checkout, to read the version
core declares there, so check out the same ref first. A release tag's version must be that
version, and the one the installed troupe prints.
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
"""The refs the docs may name besides a release tag: the latest main, or a placeholder for a commit
of your choosing."""
TAG_PREFIX = "troupe-run-v"
"""A release's tag is this and the bundle's version (install-from-tag design D1): the bundle's own
tag, since the command installs the bundle."""

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
_TAGGED = re.compile(re.escape(TAG_PREFIX) + r"(\d+\.\d+\.\d+\S*)")


class InstallCheckError(Exception):
    """A step failed. The message names the step, the command and what it printed."""


def command(repository: str, ref: str) -> str:
    """The documented install command, for a repository URL and a ref."""
    return TEMPLATE.format(repository=repository, ref=ref)


def tagged_version(ref: str) -> str | None:
    """The version a release tag names, or None when the ref isn't a release tag."""
    matched = _TAGGED.fullmatch(ref)
    return matched.group(1) if matched else None


def expected_version(ref: str, declared: str, sha: str) -> str:
    """The version the install must print: core's at the commit. A release tag must name it too."""
    tagged = tagged_version(ref)
    if tagged is not None and tagged != declared:
        raise InstallCheckError(
            f"--ref {ref}: the tag names version {tagged}, but core declares {declared} at {sha}. "
            "The bundle and core are released at one version, so the tag or the linked group is "
            "wrong."
        )
    return declared


def confirm_printed(shown: str, version: str, ref: str, sha: str) -> None:
    """Refused, naming what was printed, unless `troupe --version` names the expected version."""
    if f"troupe {version} " in shown:
        return
    tagged = tagged_version(ref) is not None
    named = f"the version {ref} names" if tagged else f"the version core declares at {sha}"
    raise InstallCheckError(
        f"troupe --version: printed {shown.strip()!r}, not troupe {version}, {named}."
    )


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


def source(root: Path, ref: str, sha: str, hosted: bool) -> tuple[str, str]:
    """Where to install from, and the ref to give it: GitHub with the ref exactly as the docs give
    it, or the checkout by its resolved commit (install-from-tag design D4)."""
    return (REPOSITORY, ref) if hosted else (repository_url(root), sha)


def check(root: Path, ref: str, python: str | None, hosted: bool = False) -> str:
    """Install `ref` the documented way and perform with it. Returns the run's line."""
    sha = resolve(root, ref)
    version = expected_version(ref, core_version(root, sha), sha)
    repository, install_ref = source(root, ref, sha, hosted)
    with scratch() as place:
        tools = Tools(directory=place / "tools", bin=place / "bin")
        env = tools.environment(os.environ)
        run(
            "install",
            [_program("uv"), *install_arguments(repository, install_ref, python)],
            place,
            env,
            INSTALL_TIMEOUT,
        )
        troupe = _program("troupe", path=str(tools.bin))
        shown = run("troupe --version", [troupe, "--version"], place, env, COMMAND_TIMEOUT)
        confirm_printed(shown, version, ref, sha)
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
        description=(
            "Install troupe the documented way, from a commit of this checkout or from GitHub, "
            "and run it."
        ),
    )
    parser.add_argument(
        "--ref", default="HEAD", help="the commit, branch or tag to install (default: HEAD)"
    )
    parser.add_argument("--python", help="the Python to install it on (default: uv's choice)")
    parser.add_argument(
        "--hosted",
        action="store_true",
        help=f"install from {REPOSITORY} with the ref as given, as the docs do "
        "(default: this checkout)",
    )
    arguments = parser.parse_args(argv)
    try:
        line = check(ROOT, arguments.ref, arguments.python, arguments.hosted)
    except InstallCheckError as error:
        print(f"install check: {error}", file=sys.stderr)
        return 1
    print(f"install check: installed and performed ({line})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
