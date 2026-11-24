"""Task 7.1: running the check turns the git hooks on by default.

Its tests that stay in their own process are in unit/test_check_activation_unit.py."""

from collections.abc import Callable

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
