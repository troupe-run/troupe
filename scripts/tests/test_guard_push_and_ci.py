"""Tasks 7.2-7.3: commit messages checked before a push, and every git-level rule re-checked on
GitHub for a push or a pull request."""

from collections.abc import Callable
from pathlib import Path

from conftest import Repo, git

import guard


def with_remote(repo: Repo, tmp_path: Path) -> Path:
    remote = tmp_path / f"{repo.path.name}-remote.git"
    git(tmp_path, "init", "-q", "--bare", str(remote))
    git(repo.path, "remote", "add", "origin", str(remote))
    git(repo.path, "push", "-q", "origin", "main")
    return remote


def commit_without_hooks(repo: Repo, message: str, name: str) -> str:
    """A commit made with --no-verify: exactly what the push and CI checks must still catch."""
    repo.write(name, f"{name}\n")
    git(repo.path, "add", name)
    git(repo.path, "commit", "-q", "--no-verify", "-m", message)
    return repo.head()


# Task 7.2: pre-push


def test_a_push_carrying_a_non_conventional_commit_is_refused_naming_it(
    make_repo: Callable[[], Repo], tmp_path: Path
) -> None:
    repo = make_repo()
    repo.hooks_on()
    with_remote(repo, tmp_path)
    repo.change("add-thing")
    repo.switch("add-thing")
    git(repo.path, "add", "-A")
    git(repo.path, "commit", "-q", "-m", "docs(openspec): plan add-thing")
    bad = commit_without_hooks(repo, "Add a thing", "a.txt")
    result = git(repo.path, "push", "-u", "origin", "add-thing", check=False)
    assert result.returncode != 0
    assert "guard: commit-message:" in result.stderr
    assert bad[:7] in result.stderr
    assert "'Add a thing'" in result.stderr
    remote_branches = git(repo.path, "ls-remote", "--heads", "origin").stdout
    assert "add-thing" not in remote_branches


def test_a_push_of_conventional_commits_goes_ahead(
    make_repo: Callable[[], Repo], tmp_path: Path
) -> None:
    repo = make_repo()
    repo.hooks_on()
    with_remote(repo, tmp_path)
    repo.change("add-thing")
    repo.switch("add-thing")
    result = repo.commit("feat(thing): add a thing")
    assert result.returncode == 0, result.stderr
    pushed = git(repo.path, "push", "-u", "origin", "add-thing", check=False)
    assert pushed.returncode == 0, pushed.stderr


def test_only_commits_new_to_the_remote_are_checked(
    make_repo: Callable[[], Repo], tmp_path: Path
) -> None:
    repo = make_repo()
    with_remote(repo, tmp_path)
    commit_without_hooks(repo, "Old bad message already on the remote", "old.txt")
    git(repo.path, "push", "-q", "--no-verify", "origin", "main")
    good = commit_without_hooks(repo, "fix: a new, conforming commit", "new.txt")
    remote_main = git(repo.path, "rev-parse", "origin/main").stdout.strip()
    assert guard.commits_in_range(repo.path, remote_main, good) == [good]


def test_deleting_a_remote_branch_checks_nothing(make_repo: Callable[[], Repo]) -> None:
    repo = make_repo()
    line = f"(delete) {'0' * 40} refs/heads/gone {'1' * 40}"
    assert guard.run_pre_push(repo.path, [line]) == 0


# Task 7.3: the same rules on GitHub


def pr_repo(make_repo: Callable[[], Repo], tmp_path: Path) -> tuple[Repo, str]:
    repo = make_repo()
    with_remote(repo, tmp_path)
    base = repo.head()
    repo.change("add-thing")
    repo.switch("add-thing")
    git(repo.path, "add", "-A")
    git(repo.path, "commit", "-q", "-m", "docs(openspec): plan add-thing")
    return repo, base


def test_a_conforming_pull_request_passes(make_repo: Callable[[], Repo], tmp_path: Path) -> None:
    repo, base = pr_repo(make_repo, tmp_path)
    commit_without_hooks(repo, "feat(thing): add a thing", "a.txt")
    assert guard.run_ci(repo.path, base, repo.head(), "add-thing") == []


def test_a_pull_request_with_a_no_verify_bad_message_fails_naming_the_commit(
    make_repo: Callable[[], Repo], tmp_path: Path
) -> None:
    repo, base = pr_repo(make_repo, tmp_path)
    bad = commit_without_hooks(repo, "Add a thing", "a.txt")
    [refusal] = guard.run_ci(repo.path, base, repo.head(), "add-thing")
    assert refusal.rule == "commit-message"
    assert bad[:7] in refusal.problem


def test_a_pull_request_from_a_branch_with_no_change_fails(
    make_repo: Callable[[], Repo], tmp_path: Path
) -> None:
    repo = make_repo()
    with_remote(repo, tmp_path)
    base = repo.head()
    repo.switch("no-change")
    commit_without_hooks(repo, "feat: something", "a.txt")
    [refusal] = guard.run_ci(repo.path, base, repo.head(), "no-change")
    assert refusal.rule == "commit-branch-change"


def test_a_push_to_main_checks_messages_but_not_the_branch_rule(
    make_repo: Callable[[], Repo], tmp_path: Path
) -> None:
    repo = make_repo()
    with_remote(repo, tmp_path)
    before = repo.head()
    commit_without_hooks(repo, "fix: on main", "a.txt")
    assert guard.run_ci(repo.path, before, repo.head(), "main") == []
    commit_without_hooks(repo, "Bad on main", "b.txt")
    [refusal] = guard.run_ci(repo.path, before, repo.head(), "main")
    assert refusal.rule == "commit-message"


def test_a_new_branch_push_checks_everything_not_on_the_remote(
    make_repo: Callable[[], Repo], tmp_path: Path
) -> None:
    repo, _ = pr_repo(make_repo, tmp_path)
    bad = commit_without_hooks(repo, "Add a thing", "a.txt")
    [refusal] = guard.run_ci(repo.path, None, repo.head(), "add-thing")
    assert bad[:7] in refusal.problem


def test_an_archived_change_with_an_unticked_task_fails(
    make_repo: Callable[[], Repo], tmp_path: Path
) -> None:
    repo, base = pr_repo(make_repo, tmp_path)
    repo.change("add-thing", archived_on="2026-10-11", tasks="- [ ] 1.1 not done\n")
    git(repo.path, "add", "-A")
    git(repo.path, "commit", "-q", "--no-verify", "-m", "docs(openspec): archive add-thing")
    rules = [d.rule for d in guard.run_ci(repo.path, base, repo.head(), "add-thing")]
    assert rules == ["archive-incomplete"]


def test_a_local_override_doesn_t_excuse_anything_on_github(
    make_repo: Callable[[], Repo], tmp_path: Path
) -> None:
    repo, base = pr_repo(make_repo, tmp_path)
    commit_without_hooks(repo, "Add a thing", "a.txt")
    guard.grant_override(repo.path, "commit-message", "trying to slip one through")
    [refusal] = guard.run_ci(repo.path, base, repo.head(), "add-thing")
    assert refusal.rule == "commit-message"
