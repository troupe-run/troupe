"""Task 2.4: the git hooks end to end, making real commits in a temporary repository."""

from collections.abc import Callable

from conftest import FAILING_CHECK, Repo


def test_a_commit_on_main_is_refused_and_leaves_no_commit(make_repo: Callable[[], Repo]) -> None:
    repo = make_repo()
    repo.hooks_on()
    before = repo.head()
    repo.write("a.txt", "a\n")
    result = repo.commit("feat: add a")
    assert result.returncode != 0
    assert "guard: commit-on-main:" in result.stderr
    assert repo.head() == before


def test_a_commit_on_a_branch_without_its_change_is_refused(make_repo: Callable[[], Repo]) -> None:
    repo = make_repo()
    repo.hooks_on()
    repo.switch("add-thing")
    before = repo.head()
    repo.write("a.txt", "a\n")
    result = repo.commit("feat: add a")
    assert result.returncode != 0
    assert "guard: commit-branch-change:" in result.stderr
    assert repo.head() == before


def test_a_non_conventional_message_is_refused_and_leaves_no_commit(
    make_repo: Callable[[], Repo],
) -> None:
    repo = make_repo()
    repo.hooks_on()
    repo.change("add-thing")
    repo.switch("add-thing")
    before = repo.head()
    result = repo.commit("Add a thing")
    assert result.returncode != 0
    assert "guard: commit-message:" in result.stderr
    assert repo.head() == before


def test_a_failing_check_refuses_the_commit(make_repo: Callable[[], Repo]) -> None:
    repo = make_repo()
    repo.hooks_on(check_script=FAILING_CHECK)
    repo.change("add-thing")
    repo.switch("add-thing")
    before = repo.head()
    result = repo.commit("feat: add a thing")
    assert result.returncode != 0
    assert "guard: commit-checks: the mypy --strict gate failed." in result.stderr
    assert repo.head() == before


def test_a_commit_that_meets_every_rule_is_made(make_repo: Callable[[], Repo]) -> None:
    repo = make_repo()
    repo.hooks_on()
    repo.change("add-thing")
    repo.switch("add-thing")
    before = repo.head()
    result = repo.commit("feat(thing): add a thing")
    assert result.returncode == 0, result.stderr
    assert repo.head() != before
