"""Temporary git repositories for the tests of scripts/check.py, and stopping a process tree a test
gives up on. The guard's own tests live in troupe-run/infrastructure, where the guard is
maintained."""

import contextlib
import os
import signal
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

SCRIPTS = Path(__file__).resolve().parents[1]
REPO = SCRIPTS.parent
sys.path.insert(0, str(SCRIPTS))

import python_versions  # noqa: E402  (found through the path above)

BOUND = python_versions.bound(REPO)
"""The root's requires-python. Tests read it, so widening the bound needs no test edits
(python-3-14-3-15 design D3)."""
SUPPORTED = python_versions.supported(REPO)
LOWEST, HIGHEST = SUPPORTED[0], SUPPORTED[-1]


def minor_after(version: str, steps: int = 1) -> str:
    """The minor version steps after version: 3.13 -> 3.14."""
    return f"3.{int(version.split('.')[1]) + steps}"


def listed(versions: list[str]) -> str:
    """Versions as prose: 3.12, 3.13 and 3.14."""
    return versions[0] if len(versions) == 1 else f"{', '.join(versions[:-1])} and {versions[-1]}"


def clean_env() -> dict[str, str]:
    """No inherited repository-location variables: tests may run inside a real pre-commit hook."""
    import guard

    return guard._git_env()


def git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=check, env=clean_env()
    )


class Repo:
    """A throwaway git repository with one commit on main."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def write(self, relative: str, text: str) -> Path:
        target = self.path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        return target


@pytest.fixture
def make_repo(tmp_path: Path) -> Callable[[], Repo]:
    counter = iter(range(1000))

    def make() -> Repo:
        path = tmp_path / f"repo{next(counter)}"
        path.mkdir()
        git(path, "init", "-q", "-b", "main")
        git(path, "config", "user.email", "tester@example.com")
        git(path, "config", "user.name", "Tester")
        git(path, "config", "commit.gpgsign", "false")
        repo = Repo(path)
        repo.write("README.md", "test\n")
        git(path, "add", "-A")
        git(path, "commit", "-q", "-m", "chore: initial")
        return repo

    return make


STOP_TREE_WITHIN = 30.0
"""Seconds for a killed process to be reaped once stop_tree has killed its tree."""


def _descendants(root: int) -> tuple[list[int], dict[int, int]]:
    """POSIX: ``root``'s descendants, from a snapshot of every process, and each one's group."""
    table = subprocess.run(
        ["ps", "-A", "-o", "pid=,ppid=,pgid="], capture_output=True, text=True, check=True
    ).stdout
    children: dict[int, list[int]] = {}
    groups: dict[int, int] = {}
    for line in table.splitlines():
        pid, ppid, pgid = (int(field) for field in line.split())
        children.setdefault(ppid, []).append(pid)
        groups[pid] = pgid
    found: list[int] = []
    waiting = [root]
    while waiting:
        for child in children.get(waiting.pop(), []):
            if child not in found:
                found.append(child)
                waiting.append(child)
    return found, groups


def stop_tree(process: "subprocess.Popen[Any]") -> None:
    """Kill ``process`` and everything it started, for a test that gives up on it (#364).

    The tree is read before anything is killed: once a process dies its children are re-parented
    and can't be found from it. On POSIX each process group in the tree is killed (a flake hunt's
    rounds and load each run in a session of their own), then each pid; the test's own group is
    never touched. On Windows taskkill follows the parent links."""
    if sys.platform == "win32":
        if process.poll() is None:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                capture_output=True,
                check=False,
            )
    else:
        descendants, groups = _descendants(process.pid)
        ours = os.getpgrp()
        tree = [process.pid, *descendants]
        for group in {groups.get(pid, pid) for pid in tree} - {ours}:
            with contextlib.suppress(OSError):
                os.killpg(group, signal.SIGKILL)
        for pid in descendants:
            with contextlib.suppress(OSError):
                os.kill(pid, signal.SIGKILL)
    with contextlib.suppress(OSError):
        process.kill()
    process.wait(STOP_TREE_WITHIN)


def run_within(
    command: list[str],
    seconds: float,
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> "subprocess.CompletedProcess[bytes]":
    """Run ``command`` to its end, as subprocess.run with captured output does, but give up after
    ``seconds`` by stopping its whole tree, then fail with what it wrote so far (#364)."""
    process = subprocess.Popen(
        command, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    try:
        stdout, stderr = process.communicate(timeout=seconds)
    except subprocess.TimeoutExpired:
        stop_tree(process)
        stdout, stderr = process.communicate()
        shown = (stdout + stderr).decode("utf-8", errors="backslashreplace")[-4000:]
        raise AssertionError(
            f"{command[1] if len(command) > 1 else command[0]} didn't end within {seconds:g}s, "
            f"so its tree was stopped; its output so far:\n{shown}"
        ) from None
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
