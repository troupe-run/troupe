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
