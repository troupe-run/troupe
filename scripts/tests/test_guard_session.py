"""Task 5.1: the SessionStart entry point activates the git hooks and reports the workflow."""

import io
import json
from collections.abc import Callable

from conftest import Repo, git

import guard


def session_start(repo: Repo) -> str:
    stream = io.StringIO()
    assert guard.run_claude_session_start(repo.path, stdout=stream) == 0
    output = json.loads(stream.getvalue())
    specific = output["hookSpecificOutput"]
    assert specific["hookEventName"] == "SessionStart"
    context: str = specific["additionalContext"]
    return context


def hooks_path(repo: Repo) -> str:
    return git(repo.path, "config", "--get", "core.hooksPath", check=False).stdout.strip()


def test_inactive_git_hooks_are_activated_and_the_session_is_told(
    make_repo: Callable[[], Repo],
) -> None:
    repo = make_repo()
    assert hooks_path(repo) == ""
    context = session_start(repo)
    assert hooks_path(repo) == ".githooks"
    assert "Activated the repository's git hooks (core.hooksPath was unset" in context


def test_hooks_pointing_elsewhere_are_reset_to_the_repository_s_hooks(
    make_repo: Callable[[], Repo],
) -> None:
    repo = make_repo()
    git(repo.path, "config", "core.hooksPath", "/somewhere/else")
    context = session_start(repo)
    assert hooks_path(repo) == ".githooks"
    assert "was /somewhere/else" in context


def test_already_active_hooks_are_left_alone_and_not_mentioned(
    make_repo: Callable[[], Repo],
) -> None:
    repo = make_repo()
    git(repo.path, "config", "core.hooksPath", ".githooks")
    assert "Activated" not in session_start(repo)


def test_the_context_states_the_workflow(make_repo: Callable[[], Repo]) -> None:
    context = session_start(make_repo())
    assert "issue -> OpenSpec change" in context
    assert "Conventional Commits" in context
    assert "Only the owner can grant an override" in context


def test_the_context_says_when_the_branch_has_no_matching_change(
    make_repo: Callable[[], Repo],
) -> None:
    context = session_start(make_repo())
    assert "Branch 'main' has no matching OpenSpec change" in context


def test_the_context_says_when_the_branch_matches_a_change(make_repo: Callable[[], Repo]) -> None:
    repo = make_repo()
    repo.change("add-thing")
    repo.switch("add-thing")
    context = session_start(repo)
    assert "Branch 'add-thing' matches the OpenSpec change openspec/changes/add-thing" in context
