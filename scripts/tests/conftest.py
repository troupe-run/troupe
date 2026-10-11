"""Shared helpers for the guard tests: temporary git repositories shaped like this one."""

import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1]
REPO = SCRIPTS.parent
sys.path.insert(0, str(SCRIPTS))

PASSING_CHECK = 'print("check: all gates passed")\n'
FAILING_CHECK = (
    'import sys\nprint("check: mypy --strict failed (exit 1) after 0.1s")\nsys.exit(1)\n'
)


def clean_env() -> dict[str, str]:
    """No inherited GIT_* variables: tests may run inside a real pre-commit hook."""
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=check, env=clean_env()
    )


class Repo:
    """A throwaway repository with this repo's guard script and git hooks copied in."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def write(self, relative: str, text: str) -> Path:
        target = self.path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        return target

    def change(
        self, name: str, *, archived_on: str | None = None, tasks: str = "- [x] 1.1 done\n"
    ) -> Path:
        base = (
            f"openspec/changes/archive/{archived_on}-{name}"
            if archived_on
            else f"openspec/changes/{name}"
        )
        return self.write(f"{base}/tasks.md", tasks).parent

    def switch(self, branch: str) -> None:
        git(self.path, "switch", "-q", "-c", branch)

    def commit(self, message: str, *paths: str) -> subprocess.CompletedProcess[str]:
        git(self.path, "add", *(paths or ("-A",)))
        return git(self.path, "commit", "-q", "-m", message, check=False)

    def head(self) -> str:
        return git(self.path, "rev-parse", "HEAD").stdout.strip()

    def hooks_on(self, check_script: str = PASSING_CHECK) -> None:
        shutil.copytree(REPO / ".githooks", self.path / ".githooks")
        self.write("scripts/guard.py", (SCRIPTS / "guard.py").read_text(encoding="utf-8"))
        self.write("scripts/check.py", check_script)
        git(self.path, "add", "-A")
        git(self.path, "commit", "-q", "-m", "chore: add the guard")
        git(self.path, "config", "core.hooksPath", ".githooks")


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
