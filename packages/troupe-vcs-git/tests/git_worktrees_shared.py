"""Helpers that test_git_worktrees.py shares with other test modules."""

import subprocess
from pathlib import Path

import pytest

from gitrepo import AUTHOR, Repo, make_repo
from troupe.core.files import clone_file
from troupe_vcs_git import GitAdapter


def adapter(repo: Repo, **options: object) -> GitAdapter:
    return GitAdapter(repo.path, source=repo.env, **options)  # type: ignore[arg-type]


@pytest.fixture(name="repo")
def repo_fixture(tmp_path: Path) -> Repo:
    repo = make_repo(tmp_path)
    put(repo, "src/a.txt", "one\n")
    put(repo, "src/b.txt", "bee\n")
    put(repo, ".troupe/events/x.jsonl", "{}\n")
    put(repo, ".gitignore", "build/\n")
    repo.commit_all("base")
    return repo


def put(repo: Repo, relative: str, text: str) -> Path:
    """Write ``text`` as UTF-8 bytes exactly, so a commit holds LF on every OS (write_text would
    write CRLF on Windows)."""
    path = repo.path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    return path


def git_in(repo: Repo, cwd: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],  # noqa: S607
        cwd=cwd,
        env={**repo.env, **AUTHOR},
        capture_output=True,
        check=True,
    )
    return completed.stdout.decode("utf-8")


def worktree(repo: Repo, tmp_path: Path, name: str = "wt") -> tuple[GitAdapter, Path, str]:
    """A filled worktree of ``repo`` at its HEAD, with the baseline its diff is taken from."""
    git = adapter(repo)
    path = repo.path / ".troupe" / "local" / "worktrees" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    base = git.head()
    assert base is not None
    git.add_worktree(path, base)
    filled = git.fill_worktree(path, clone_file, frozenset(git.differing_from_head()))
    return git, path, filled.baseline
