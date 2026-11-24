"""The repositories conftest's make_repo builds for the check's tests: one commit on main, a clean
status, and each one its own (theatre-template-and-guard-xdist design D3)."""

from collections.abc import Callable
from pathlib import Path

import pytest
from conftest import Repo, git


def test_a_repository_has_one_commit_on_main_and_a_clean_status(
    make_repo: Callable[[], Repo],
) -> None:
    repo = make_repo()

    assert git(repo.path, "rev-list", "--count", "HEAD").stdout == "1\n"
    assert git(repo.path, "symbolic-ref", "HEAD").stdout == "refs/heads/main\n"
    assert git(repo.path, "log", "--format=%s").stdout == "chore: initial\n"
    # diff-files doesn't refresh the index, so a stat-dirty file would be listed here.
    assert git(repo.path, "diff-files", "--name-only").stdout == ""
    assert git(repo.path, "status", "--porcelain").stdout == ""


def test_two_repositories_are_independent(make_repo: Callable[[], Repo]) -> None:
    first, second = make_repo(), make_repo()
    base = git(second.path, "rev-parse", "HEAD").stdout

    first.write("README.md", "changed\n")
    git(first.path, "commit", "-q", "-am", "chore: change")

    assert first.path != second.path
    assert git(second.path, "rev-parse", "HEAD").stdout == base
    assert (second.path / "README.md").read_text(encoding="utf-8") == "test\n"


def test_a_lock_file_in_the_template_is_left_out_of_the_copy(
    request: pytest.FixtureRequest, make_repo: Callable[[], Repo]
) -> None:
    # Only this test asks for the template, to put in the lock git's background maintenance can
    # hold for a moment after the template's commit; a test that writes into it changes every later
    # copy, so it's removed again.
    template: Path = request.getfixturevalue("_repo_template")
    lock = template / ".git" / "objects" / "maintenance.lock"
    lock.write_text("", encoding="utf-8")
    try:
        repo = make_repo()
    finally:
        lock.unlink()

    assert not (repo.path / ".git" / "objects" / "maintenance.lock").exists()
    assert git(repo.path, "status", "--porcelain").stdout == ""
