"""Temporary git repositories for the tests of scripts/check.py. The guard's own tests live in
troupe-run/infrastructure, where the guard is maintained."""

import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

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
