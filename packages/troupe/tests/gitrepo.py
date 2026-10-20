"""Real git repositories for tests, isolated from the machine's own git configuration.

Each repository gets its own HOME, so the user's global config, hooks and credentials never leak
into a test, and a test can set a global config of its own. Commits use a fixed author.
"""

import os
import subprocess
import sys
import time
from pathlib import Path

AUTHOR = {
    "GIT_AUTHOR_NAME": "Test Author",
    "GIT_AUTHOR_EMAIL": "author@example.com",
    "GIT_COMMITTER_NAME": "Test Author",
    "GIT_COMMITTER_EMAIL": "author@example.com",
}


def past_the_racy_window() -> int:
    """A wall clock an hour ahead, for a GitAdapter's ``now``: no file looks recently changed, so
    no read is racy and the cache rests on the token's stats alone (cache-vcs-state design D4)."""
    return time.time_ns() + 3600 * 1_000_000_000


def isolated_environment(home: Path) -> dict[str, str]:
    """An environment for git with ``home`` as its home, and nothing of this machine's config."""
    home.mkdir(parents=True, exist_ok=True)
    env = {
        "PATH": os.environ["PATH"],
        "HOME": str(home),
        "USERPROFILE": str(home),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "GIT_CONFIG_NOSYSTEM": "1",
    }
    if sys.platform == "win32":
        env["SYSTEMROOT"] = os.environ["SYSTEMROOT"]
    return env


class Repo:
    """A git repository at ``path``, driven with an isolated environment."""

    def __init__(self, path: Path, env: dict[str, str]) -> None:
        self.path = path
        self.env = env

    def git(self, *args: str) -> str:
        completed = subprocess.run(
            ["git", *args],  # noqa: S607 - git from the test environment's PATH
            cwd=self.path,
            env={**self.env, **AUTHOR},
            capture_output=True,
            check=False,
        )
        if completed.returncode != 0:
            message = completed.stderr.decode("utf-8", "replace")
            raise AssertionError(f"git {' '.join(args)} failed: {message}")
        return completed.stdout.decode("utf-8")

    def write(self, relative: str, text: str) -> Path:
        path = self.path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def commit_all(self, message: str = "commit") -> str:
        self.git("add", "-A")
        self.git("commit", "-q", "--allow-empty", "-m", message)
        return self.git("rev-parse", "HEAD").strip()


def make_repo(root: Path, name: str = "theatre", branch: str = "main") -> Repo:
    """A new repository at ``root / name``, with its own HOME at ``root / (name + '-home')``."""
    path = root / name
    path.mkdir(parents=True)
    repo = Repo(path, isolated_environment(root / f"{name}-home"))
    repo.git("init", "-q", "-b", branch)
    return repo


def clone(repo: Repo, root: Path, name: str) -> Repo:
    """A clone of ``repo`` at ``root / name``, sharing its isolated environment."""
    path = root / name
    subprocess.run(
        ["git", "clone", "-q", str(repo.path), str(path)],  # noqa: S607
        env={**repo.env, **AUTHOR},
        check=True,
        capture_output=True,
    )
    return Repo(path, repo.env)
