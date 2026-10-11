"""Task 1.2: which OpenSpec change matches the current branch (design D3)."""

from collections.abc import Callable
from pathlib import Path

from conftest import Repo, git

import guard


def test_an_active_change_with_the_branch_s_name_matches(make_repo: Callable[[], Repo]) -> None:
    repo = make_repo()
    change = repo.change("add-thing")
    repo.switch("add-thing")
    assert guard.current_branch(repo.path) == "add-thing"
    assert guard.matching_change(repo.path, "add-thing") == change


def test_a_change_archived_on_the_branch_matches(make_repo: Callable[[], Repo]) -> None:
    repo = make_repo()
    archived = repo.change("add-thing", archived_on="2026-10-11")
    assert guard.matching_change(repo.path, "add-thing") == archived


def test_a_branch_with_no_change_matches_nothing(make_repo: Callable[[], Repo]) -> None:
    repo = make_repo()
    repo.change("other-thing")
    assert guard.matching_change(repo.path, "add-thing") is None


def test_a_similar_archived_name_doesn_t_match(make_repo: Callable[[], Repo]) -> None:
    repo = make_repo()
    repo.change("add-thing-two", archived_on="2026-10-11")
    assert guard.matching_change(repo.path, "add-thing") is None


def test_main_never_matches_even_with_a_change_named_main(make_repo: Callable[[], Repo]) -> None:
    repo = make_repo()
    repo.change("main")
    assert guard.matching_change(repo.path, "main") is None


def test_the_branch_is_read_from_the_rebase_state_while_head_is_detached(
    make_repo: Callable[[], Repo],
) -> None:
    repo = make_repo()
    repo.switch("add-thing")
    git_dir = git(repo.path, "rev-parse", "--absolute-git-dir").stdout.strip()
    git(repo.path, "checkout", "-q", "--detach")
    state = repo.path / ".git" / "rebase-merge"
    assert state.parent == Path(git_dir)  # git prints C:/... on Windows; compare as paths
    state.mkdir()
    (state / "head-name").write_text("refs/heads/add-thing\n", encoding="utf-8")
    assert guard.current_branch(repo.path) == "add-thing"


def test_a_plain_detached_head_has_no_branch(make_repo: Callable[[], Repo]) -> None:
    repo = make_repo()
    git(repo.path, "checkout", "-q", "--detach")
    assert guard.current_branch(repo.path) is None
