"""Tasks 2.1-2.3: the git-level rules as pure decisions."""

from collections.abc import Callable

import pytest
from conftest import FAILING_CHECK, PASSING_CHECK, Repo, git
from hypothesis import given
from hypothesis import strategies as st

import guard

# Rule: commit-message


@pytest.mark.parametrize(
    "message",
    [
        "feat(cli): add --version",
        "fix: handle an empty file",
        "feat(platform)!: change the lock API",
        "refactor!: drop the old path",
        "docs(openspec): plan the change\n\nA body.\n\nCo-Authored-By: x <y@z>",
        "# a comment line git leaves in\nci: run on Windows",
        "fixup! feat(cli): add --version",
        "squash! fix: handle an empty file",
        "amend! docs: tidy",
    ],
)
def test_conventional_and_autosquash_messages_are_accepted(message: str) -> None:
    assert guard.commit_message(message) == guard.ALLOW


@pytest.mark.parametrize(
    ("message", "in_fix"),
    [
        ("Add the version flag", "feat(cli): add --version"),
        ("feature: add --version", "feat, fix, docs"),
        ("feat:missing space", "Types:"),
        ("Feat: capitalised type", "Types:"),
        ('Revert "feat(cli): add --version"', "revert: <what is reverted>"),
        ("Merge branch 'main' into x", "rebase onto the target"),
        ("", "Types:"),
    ],
)
def test_other_messages_are_refused_with_the_expected_form(message: str, in_fix: str) -> None:
    decision = guard.commit_message(message)
    assert decision.rule == "commit-message"
    assert in_fix in decision.fix


SUBJECT = st.text(alphabet="abcdefghijklmnopqrstuvwxyz -,.'0123456789", min_size=1).filter(
    lambda s: not s.startswith(" ")
)
SCOPE = st.from_regex(r"\A[a-z0-9][a-z0-9-]{0,12}\Z")


@given(
    kind=st.sampled_from(guard.COMMIT_TYPES),
    scope=st.none() | SCOPE,
    breaking=st.booleans(),
    subject=SUBJECT,
)
def test_any_well_formed_conventional_first_line_is_accepted(
    kind: str, scope: str | None, breaking: bool, subject: str
) -> None:
    line = f"{kind}{f'({scope})' if scope else ''}{'!' if breaking else ''}: {subject}"
    assert guard.commit_message(line) == guard.ALLOW


@given(line=st.text(alphabet=st.characters(blacklist_characters=":\n\r#"), min_size=1))
def test_a_first_line_without_a_colon_is_always_refused(line: str) -> None:
    assert guard.commit_message(line).rule == "commit-message"


# Rules: commit-on-main, commit-branch-change


def test_committing_on_main_is_refused() -> None:
    decision = guard.commit_on_main("main")
    assert decision.rule == "commit-on-main"
    assert "git switch -c" in decision.fix


def test_committing_on_another_branch_passes_the_main_rule() -> None:
    assert guard.commit_on_main("add-thing") == guard.ALLOW


def test_a_branch_without_a_matching_change_is_refused(make_repo: Callable[[], Repo]) -> None:
    repo = make_repo()
    decision = guard.commit_branch_change(repo.path, "add-thing")
    assert decision.rule == "commit-branch-change"
    assert "/opsx:propose add-thing" in decision.fix


def test_a_branch_with_its_change_is_allowed(make_repo: Callable[[], Repo]) -> None:
    repo = make_repo()
    repo.change("add-thing")
    assert guard.commit_branch_change(repo.path, "add-thing") == guard.ALLOW


def test_a_detached_head_is_refused(make_repo: Callable[[], Repo]) -> None:
    assert guard.commit_branch_change(make_repo().path, None).rule == "commit-branch-change"


# Rule: archive-incomplete


def test_staging_an_archived_change_with_an_unticked_task_is_refused(
    make_repo: Callable[[], Repo],
) -> None:
    repo = make_repo()
    repo.change(
        "add-thing", archived_on="2026-10-11", tasks="- [x] 1.1 done\n- [ ] 1.2 write the docs\n"
    )
    git(repo.path, "add", "-A")
    staged = git(repo.path, "diff", "--cached", "--name-only").stdout.splitlines()
    decision = guard.unticked_archived_tasks(staged, guard.ReadStaged(repo.path))
    assert decision.rule == "archive-incomplete"
    assert "2026-10-11-add-thing" in decision.problem
    assert "1.2 write the docs" in decision.problem


@pytest.mark.parametrize("marker", ["[~]", "[-]", "[]"])
def test_any_marker_other_than_x_counts_as_unticked(
    make_repo: Callable[[], Repo], marker: str
) -> None:
    repo = make_repo()
    repo.change("add-thing", archived_on="2026-10-11", tasks=f"- {marker} 1.1 half done\n")
    git(repo.path, "add", "-A")
    staged = git(repo.path, "diff", "--cached", "--name-only").stdout.splitlines()
    assert guard.unticked_archived_tasks(staged, guard.ReadStaged(repo.path)).refused


def test_an_archived_change_with_every_task_ticked_is_allowed(
    make_repo: Callable[[], Repo],
) -> None:
    repo = make_repo()
    repo.change("add-thing", archived_on="2026-10-11", tasks="- [x] 1.1 done\n- [X] 1.2 done\n")
    git(repo.path, "add", "-A")
    staged = git(repo.path, "diff", "--cached", "--name-only").stdout.splitlines()
    assert guard.unticked_archived_tasks(staged, guard.ReadStaged(repo.path)) == guard.ALLOW


def test_an_active_change_with_unticked_tasks_is_allowed(make_repo: Callable[[], Repo]) -> None:
    repo = make_repo()
    repo.change("add-thing", tasks="- [ ] 1.1 not yet\n")
    git(repo.path, "add", "-A")
    staged = git(repo.path, "diff", "--cached", "--name-only").stdout.splitlines()
    assert guard.unticked_archived_tasks(staged, guard.ReadStaged(repo.path)) == guard.ALLOW


# Rule: commit-checks


def test_unstaged_changes_to_tracked_files_are_refused(make_repo: Callable[[], Repo]) -> None:
    repo = make_repo()
    repo.write("scripts/check.py", PASSING_CHECK)
    repo.write("README.md", "changed but not staged\n")
    decision = guard.commit_checks(repo.path)
    assert decision.rule == "commit-checks"
    assert "README.md" in decision.problem
    assert "git stash --keep-index" in decision.fix


def test_a_failing_check_is_refused_naming_the_gate(make_repo: Callable[[], Repo]) -> None:
    repo = make_repo()
    repo.write("scripts/check.py", FAILING_CHECK)
    git(repo.path, "add", "-A")
    decision = guard.commit_checks(repo.path)
    assert decision.rule == "commit-checks"
    assert "mypy --strict" in decision.problem


def test_a_passing_check_with_everything_staged_is_allowed(make_repo: Callable[[], Repo]) -> None:
    repo = make_repo()
    repo.write("scripts/check.py", PASSING_CHECK)
    git(repo.path, "add", "-A")
    assert guard.commit_checks(repo.path) == guard.ALLOW
