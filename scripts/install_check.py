# /// script
# dependencies = []
# ///
"""Install troupe the documented way, from a commit or a tag, and run it (spec: installation).

Usage: uv run scripts/install_check.py [--ref REF] [--python VERSION] [--hosted]

Runs the install command the README and the user docs give, with this checkout as the repository
and REF (default HEAD) as the ref, into a tool directory of its own (install-with-uv design D4).
With --hosted it installs from GitHub instead, with REF exactly as given, as someone following
the docs would: the release install check runs it against each published troupe-run-v<version>
tag (install-from-tag design D4, D5). REF is still resolved in this checkout, to read core's and the
bundle's pyproject.toml there, so check out the same ref first. A bundle tag installs with
--no-sources, so each component comes from the bundle's pins: the tag's version must be the
bundle's, every component must be pinned, and the installed troupe must print the version core is
pinned at (release-each-package design D3, D10). Any other ref installs everything from that
commit, and troupe must print core's version there.
Then it runs the installed `troupe --version`, and a scripted performance in a new theatre outside
the checkout, as "Your first performance" does. Then it rehearses an audition on each runner that
comes as an extra, which that install must refuse, naming the extra; installs troupe-run[all] into
a second tool directory, unless the ref's bundle has no 'all' extra; and rehearses an audition on
every runner troupe knows with it, so every runner's dependencies are shown to install on each
platform and Python (runner-extras design D9). Nothing is installed into your own uv tool directory
or onto your path, and everything is removed afterwards. CI runs it against the commit under test
on every platform and Python (design D5). Each install retries a failing package index HTTP_RETRIES
times, unless UV_HTTP_RETRIES is already set, so a short outage on one runner doesn't fail it
(install-check-network-retries design D2).

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

from bundle import ALL, RUNNER_TABLE, Runner, parse_runner_table
from release_config import REPOSITORY, distinct_requirements, read_pin, requirement_name

ROOT = Path(__file__).resolve().parent.parent
SUBDIRECTORY = "packages/troupe-run"
"""The bundle (design D1), which installs troupe with everything it bundles."""
TEMPLATE = 'uv tool install {flags}"{name}git+{repository}@{ref}#subdirectory=' + SUBDIRECTORY + '"'
"""The install command the README, the user docs and this check use (design D3). For a bundle tag
its flags are --no-sources, so each component comes from the tag's pins rather than the tag's
own workspace (release-each-package design D3); for any other ref, none. With extras, its name is
`troupe-run[<extras>] @ ` before the URL; without, nothing (runner-extras design D10)."""
PINNED = "--no-sources "
CORE = "troupe"
DOCUMENTED_REFS = ("main", "<commit>")
"""The refs the docs may name besides a release tag: the latest main, or a placeholder for a commit
of your choosing."""
TAG_PREFIX = "troupe-run-v"
"""A release's tag is this and the bundle's version (install-from-tag design D1): the bundle's own
tag, since the command installs the bundle."""

WOULD_CHANGE = 3
"""The exit code of a rehearsal that would succeed and change something: troupe's
ExitCode.WOULD_CHANGE, which a test keeps this equal to (this script imports nothing of
troupe's)."""

INSTALL_TIMEOUT = 600.0
"""Seconds the install may take: the first one resolves and builds every package."""
COMMAND_TIMEOUT = 120.0
"""Seconds each other command may take, the scripted performance included."""
HTTP_RETRIES = 6
"""How many times uv retries a request to a package index that fails with a network fault, given to
each install as UV_HTTP_RETRIES unless whoever runs the check set it (install-check-network-retries
design D1-D3). uv's default of 3 gave up on PyPI after 48.6 s on one CI runner (#375). Six, with
uv's exponential backoff (about 51 s in all) and its 10 s connect timeout, outlast about two minutes
of an unreachable index, while a CI leg that fails anyway still ends inside its 20-minute job
timeout. A failure that isn't a network fault, such as a package the index doesn't have, isn't
retried."""

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


def command(repository: str, ref: str, extras: Sequence[str] = ()) -> str:
    """The documented install command, for a repository URL, a ref and any extras."""
    flags = PINNED if tagged_version(ref) is not None else ""
    return TEMPLATE.format(flags=flags, name=_name(extras), repository=repository, ref=ref)


def _name(extras: Sequence[str]) -> str:
    return f"troupe-run[{','.join(extras)}] @ " if extras else ""


def tagged_version(ref: str) -> str | None:
    """The version a release tag names, or None when the ref isn't a release tag."""
    matched = _TAGGED.fullmatch(ref)
    return matched.group(1) if matched else None


def expected_version(ref: str, declared: str, bundle: str, sha: str) -> str:
    """The version the install must print. For a bundle tag, the version troupe-run pins core at,
    once the tag is shown to be the bundle's release with every component pinned; for any other
    ref, core's at the commit (release-each-package design D10)."""
    tagged = tagged_version(ref)
    if tagged is None:
        return declared
    project = tomllib.loads(bundle)["project"]
    if project.get("version") != tagged:
        raise InstallCheckError(
            f"--ref {ref}: the tag names version {tagged}, but troupe-run declares "
            f"{project.get('version')} at {sha}, so the tag isn't the bundle's release."
        )
    pins: dict[str, str] = {}
    bare: list[str] = []
    for extra, requirement in distinct_requirements(project):
        found = read_pin(requirement)
        if found is None:
            name = requirement_name(requirement)
            bare.append(name if extra is None else f"{name} (in its {extra!r} extra)")
        else:
            pins[found[0]] = found[1]
    if bare:
        raise InstallCheckError(
            f"--ref {ref}: troupe-run doesn't pin {', '.join(sorted(bare))} at {sha}, so "
            "--no-sources would look for them on a package index. A pinning pull request pins "
            "them, and the bundle's next release ships them."
        )
    if CORE not in pins:
        raise InstallCheckError(f"--ref {ref}: troupe-run doesn't pin {CORE} at {sha}.")
    return pins[CORE]


def runners_in(source: str, sha: str) -> list[Runner]:
    """The runners core's table names, from its module's source at a commit."""
    runners = parse_runner_table(source)
    if runners is None:
        raise InstallCheckError(
            f"read core's runners: {RUNNER_TABLE} at {sha} has no RUNNERS table to read."
        )
    return runners


def refused_in_the_base(runners: Sequence[Runner]) -> list[str]:
    """The runners an install without extras must refuse, naming their extra: those in one."""
    return [runner.name for runner in runners if runner.in_extra]


def rehearsed_with_all(runners: Sequence[Runner]) -> list[str]:
    """The runners an install of troupe-run[all] must have: every one troupe knows."""
    return [runner.name for runner in runners]


def has_all(bundle: str) -> bool:
    """Whether a bundle pyproject.toml's text has the 'all' extra: a tag made before it hasn't."""
    extras = tomllib.loads(bundle)["project"].get("optional-dependencies", {})
    return ALL in extras


def confirm_refused(runner: str, code: int, stdout: str, stderr: str) -> None:
    """Refused, naming what happened, unless rehearsing an audition on ``runner`` in the base
    install was refused, its fix naming the runner's extra (runner-extras design D9)."""
    extra = f"troupe-run[{runner}]"
    if code not in (0, WOULD_CHANGE) and extra in stderr:
        return
    raise InstallCheckError(
        f"base install: rehearsing an audition on {runner} should be refused, naming {extra}, "
        f"but it exited {code}.\nstandard output:\n{stdout}\nstandard error:\n{stderr}"
    )


def confirm_rehearsed(runner: str, code: int, stdout: str, stderr: str) -> None:
    """Refused, naming what happened, unless rehearsing an audition on ``runner`` with
    troupe-run[all] installed would succeed (runner-extras design D9)."""
    if code == WOULD_CHANGE:
        return
    raise InstallCheckError(
        f"all install: rehearsing an audition on {runner} should succeed with the would-change "
        f"code ({WOULD_CHANGE}), but it exited {code}.\nstandard output:\n{stdout}\n"
        f"standard error:\n{stderr}"
    )


def confirm_printed(shown: str, version: str, ref: str, sha: str) -> None:
    """Refused, naming what was printed, unless `troupe --version` names the expected version."""
    if f"troupe {version} " in shown:
        return
    tagged = tagged_version(ref) is not None
    named = f"the version {ref} pins troupe at" if tagged else f"the version core declares at {sha}"
    raise InstallCheckError(
        f"troupe --version: printed {shown.strip()!r}, not troupe {version}, {named}."
    )


def install_arguments(
    repository: str,
    ref: str,
    python: str | None,
    pinned: bool = False,
    extras: Sequence[str] = (),
) -> list[str]:
    """The arguments `uv` runs for the documented command, with `--python` when one is given. A
    bundle tag is pinned: it installs with --no-sources, even from the checkout by commit."""
    url = f"{_name(extras)}git+{repository}@{ref}#subdirectory={SUBDIRECTORY}"
    flags = [PINNED.strip()] if pinned else []
    return ["tool", "install", *flags, url, *(["--python", python] if python else [])]


def repository_url(root: Path) -> str:
    """The checkout as a repository uv can clone: a file URL, so any of its commits installs."""
    return root.resolve().as_uri()


@dataclass(frozen=True)
class Tools:
    """A tool directory of the check's own, and the variables that point uv at it."""

    directory: Path
    bin: Path

    def environment(self, base: Mapping[str, str]) -> dict[str, str]:
        """base, with the tool directories and uv's retry count. A retry count already in base is
        kept, even one uv can't read, so uv refuses it by name (design D3); an empty one is unset,
        as uv reads it."""
        retries = base.get("UV_HTTP_RETRIES") or str(HTTP_RETRIES)
        return {
            **base,
            "UV_TOOL_DIR": str(self.directory),
            "UV_TOOL_BIN_DIR": str(self.bin),
            "UV_HTTP_RETRIES": retries,
        }


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


def bundle_pyproject(root: Path, sha: str) -> str:
    """The bundle's pyproject.toml at a commit."""
    return run(
        "read the bundle's pins",
        [_program("git"), "show", f"{sha}:{SUBDIRECTORY}/pyproject.toml"],
        root,
        os.environ,
        COMMAND_TIMEOUT,
    )


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
    version = expected_version(ref, core_version(root, sha), bundle_pyproject(root, sha), sha)
    repository, install_ref = source(root, ref, sha, hosted)
    with scratch() as place:
        tools = Tools(directory=place / "tools", bin=place / "bin")
        env = tools.environment(os.environ)
        run(
            "install",
            [
                _program("uv"),
                *install_arguments(
                    repository, install_ref, python, pinned=tagged_version(ref) is not None
                ),
            ],
            place,
            env,
            INSTALL_TIMEOUT,
        )
        troupe = _program("troupe", path=str(tools.bin))
        shown = run("troupe --version", [troupe, "--version"], place, env, COMMAND_TIMEOUT)
        confirm_printed(shown, version, ref, sha)
        performed = _perform(place / "theatre", troupe, env)
        print(f"install check: base install performed ({performed})", flush=True)
        runners = runners_in(core_runners(root, sha), sha)
        for name in refused_in_the_base(runners):
            confirm_refused(name, *_audition(place, troupe, name, env))
            print(f"install check: base install refuses {name}, naming its extra", flush=True)
        if not has_all(bundle_pyproject(root, sha)):
            print(
                f"install check: troupe-run has no {ALL!r} extra at {sha}, so it isn't installed",
                flush=True,
            )
            return performed
        everything = Tools(directory=place / "tools-all", bin=place / "bin-all")
        run(
            f"install troupe-run[{ALL}]",
            [
                _program("uv"),
                *install_arguments(
                    repository,
                    install_ref,
                    python,
                    pinned=tagged_version(ref) is not None,
                    extras=(ALL,),
                ),
            ],
            place,
            everything.environment(os.environ),
            INSTALL_TIMEOUT,
        )
        troupe_all = _program("troupe", path=str(everything.bin))
        for name in rehearsed_with_all(runners):
            found = _audition(place, troupe_all, name, everything.environment(os.environ))
            confirm_rehearsed(name, *found)
            print(f"install check: troupe-run[{ALL}] rehearses an audition on {name}", flush=True)
        return performed


def core_runners(root: Path, sha: str) -> str:
    """Core's runner table module at a commit, as text."""
    return run(
        "read core's runners",
        [_program("git"), "show", f"{sha}:{RUNNER_TABLE}"],
        root,
        os.environ,
        COMMAND_TIMEOUT,
    )


def _audition(
    place: Path, troupe: str, runner: str, env: Mapping[str, str]
) -> tuple[int, str, str]:
    """Rehearse an audition on ``runner`` in a new repository of its own, which troupe init needs:
    its exit code, standard output and standard error. A rehearsal makes nothing, and doesn't
    start the runner, so it needs no engine or credential."""
    git = _program("git")
    where = place / f"audition-{runner}-{len(list(place.glob('audition-*')))}"
    where.mkdir()
    for step, argv in [
        ("make the audition's repository", [git, "init", "--quiet"]),
        ("set its identity", [git, "config", "user.email", "install-check@troupe.run"]),
        ("set its identity", [git, "config", "user.name", "install check"]),
    ]:
        run(step, argv, where, env, COMMAND_TIMEOUT)
    argv = [troupe, "init", "--audition", "--runner", runner, "--rehearse"]
    try:
        done = subprocess.run(
            argv,
            cwd=where,
            env=dict(env),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=COMMAND_TIMEOUT,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise InstallCheckError(
            f"rehearse an audition: `{' '.join(argv)}` didn't finish within {COMMAND_TIMEOUT:g}s."
        ) from error
    return done.returncode, done.stdout, done.stderr


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
                'actors.tester.effects.write=["out/**"]',
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
