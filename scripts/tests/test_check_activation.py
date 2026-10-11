"""Task 7.1: running the check turns the git hooks on by default."""

from collections.abc import Callable
from pathlib import Path

from conftest import Repo, git

import check


def hooks_path(repo: Repo) -> str:
    return git(repo.path, "config", "--get", "core.hooksPath", check=False).stdout.strip()


def test_the_check_turns_the_hooks_on_in_a_fresh_clone_and_says_so(
    make_repo: Callable[[], Repo],
) -> None:
    repo = make_repo()
    assert hooks_path(repo) == ""
    notice = check.activate_git_hooks(repo.path)
    assert hooks_path(repo) == ".githooks"
    assert notice is not None
    assert "Activated the repository's git hooks" in notice


def test_a_second_run_changes_nothing_and_says_nothing(make_repo: Callable[[], Repo]) -> None:
    repo = make_repo()
    check.activate_git_hooks(repo.path)
    assert check.activate_git_hooks(repo.path) is None
    assert hooks_path(repo) == ".githooks"


def test_a_directory_that_isn_t_a_git_checkout_is_left_alone(tmp_path: Path) -> None:
    assert check.activate_git_hooks(tmp_path) is None
