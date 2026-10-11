"""Tasks 4.1-4.3: overrides are granted by a person, used once, logged, and never self-granted."""

import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest
from conftest import SCRIPTS, Repo, clean_env, git

import guard


def override_dir(repo: Repo) -> Path:
    return repo.path / ".git" / guard.GUARD_DIR


def grant(repo: Repo, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPTS / "guard.py"), "override", *args],
        cwd=repo.path,
        capture_output=True,
        text=True,
        check=False,
        env=clean_env(),
    )


def log_lines(repo: Repo) -> list[dict[str, str]]:
    log = override_dir(repo) / "overrides.jsonl"
    if not log.is_file():
        return []
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]


# Task 4.1: granting


def test_granting_an_override_records_the_rule_reason_and_who(
    make_repo: Callable[[], Repo],
) -> None:
    repo = make_repo()
    result = grant(repo, "commit-on-main", "--reason", "hotfix while CI is down")
    assert result.returncode == 0, result.stderr
    record = json.loads((override_dir(repo) / "override.json").read_text(encoding="utf-8"))
    assert record["rule"] == "commit-on-main"
    assert record["reason"] == "hotfix while CI is down"
    assert record["granted_by"] == "tester@example.com"
    assert record["granted_at"]


def test_an_unknown_rule_can_t_be_overridden(make_repo: Callable[[], Repo]) -> None:
    repo = make_repo()
    assert grant(repo, "made-up-rule", "--reason", "x").returncode != 0
    assert not (override_dir(repo) / "override.json").exists()


def test_tampering_can_never_be_overridden(make_repo: Callable[[], Repo]) -> None:
    repo = make_repo()
    assert grant(repo, guard.TAMPER_RULE, "--reason", "x").returncode != 0


def test_an_override_needs_a_reason(make_repo: Callable[[], Repo]) -> None:
    repo = make_repo()
    assert grant(repo, "commit-on-main", "--reason", "  ").returncode != 0


def test_an_override_needs_an_identity(
    make_repo: Callable[[], Repo], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repo = make_repo()
    git(repo.path, "config", "--unset", "user.email")
    empty = tmp_path / "empty.gitconfig"
    empty.write_text("", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(empty))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    with pytest.raises(SystemExit, match=r"user\.email"):
        guard.grant_override(repo.path, "commit-on-main", "x")


# Task 4.2: using it once, and the log


def test_a_git_hook_override_allows_one_commit_then_the_rule_applies_again(
    make_repo: Callable[[], Repo],
) -> None:
    repo = make_repo()
    repo.hooks_on()
    assert grant(repo, "commit-on-main", "--reason", "emergency fix").returncode == 0

    repo.write("a.txt", "a\n")
    first = repo.commit("fix: emergency")
    assert first.returncode == 0, first.stderr
    [entry] = log_lines(repo)
    assert entry["rule"] == "commit-on-main"
    assert entry["reason"] == "emergency fix"
    assert entry["used_at"]
    assert "commit on main" in entry["allowed"]
    assert not (override_dir(repo) / "override.json").exists()

    repo.write("b.txt", "b\n")
    second = repo.commit("fix: another")
    assert second.returncode != 0
    assert "guard: commit-on-main:" in second.stderr


def test_an_override_for_one_rule_doesn_t_unlock_another(make_repo: Callable[[], Repo]) -> None:
    repo = make_repo()
    repo.hooks_on()
    repo.change("add-thing")
    repo.switch("add-thing")
    assert grant(repo, "commit-on-main", "--reason", "x").returncode == 0
    result = repo.commit("Not conventional")
    assert "guard: commit-message:" in result.stderr
    assert (override_dir(repo) / "override.json").exists()


def test_a_claude_rule_override_allows_one_edit_and_is_logged(
    make_repo: Callable[[], Repo],
) -> None:
    repo = make_repo()
    assert grant(repo, "edit-branch-change", "--reason", "fix a typo on main").returncode == 0
    payload: dict[str, object] = {
        "tool_name": "Edit",
        "tool_input": {"file_path": str(repo.path / "README.md")},
        "cwd": str(repo.path),
    }
    import io

    first, second = io.StringIO(), io.StringIO()
    guard.run_claude_pre_tool_use(payload, stdout=first)
    guard.run_claude_pre_tool_use(payload, stdout=second)
    assert first.getvalue() == ""
    assert "edit-branch-change" in second.getvalue()
    [entry] = log_lines(repo)
    assert entry["rule"] == "edit-branch-change"
    assert entry["allowed"].startswith("Edit ")


# Task 4.3: an agent can't grant itself one


@pytest.mark.parametrize(
    "command",
    [
        "uv run scripts/guard.py override commit-on-main --reason x",
        "python scripts/guard.py override skip-hooks --reason 'agent says so'",
        "echo '{}' > .git/troupe-guard/override.json",
        "cat .git/troupe-guard/overrides.jsonl",
    ],
)
def test_agent_commands_that_grant_or_touch_overrides_are_refused(command: str) -> None:
    [decision] = guard.shell_decisions(command, Path.cwd())
    assert decision.rule == guard.TAMPER_RULE


@pytest.mark.parametrize(
    "command",
    [
        "git commit -q -F - <<'EOF'\nfeat: document `scripts/guard.py override <rule>`\nEOF",
        "git commit -m 'docs: explain how .git/troupe-guard overrides are logged'",
    ],
)
def test_a_commit_message_that_mentions_the_override_isn_t_tampering(command: str) -> None:
    """Found live: the guard refused its own commit, whose message described the command."""
    assert not any(d.refused for d in guard.shell_decisions(command, Path.cwd()))


def test_a_tamper_refusal_isn_t_unlocked_by_a_pending_override(
    make_repo: Callable[[], Repo],
) -> None:
    repo = make_repo()
    repo.change("add-thing")
    repo.switch("add-thing")
    assert grant(repo, "skip-hooks", "--reason", "x").returncode == 0
    decision = guard.edit_decision(repo.path, ".git/troupe-guard/override.json", "add-thing")
    assert not guard.consume_override(repo.path, decision, "edit")
    assert (override_dir(repo) / "override.json").exists()
