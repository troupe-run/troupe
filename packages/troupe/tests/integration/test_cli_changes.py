"""troupe diff, accept and discard, and a worktree run's perform, on the command line (spec: cli,
run-workspaces; worktree-stage design D6).

Its tests that stay in their own process are in unit/test_cli_changes_unit.py."""

import json
import re
import subprocess
from pathlib import Path

import pytest

from cli_runs_shared import cli, configure
from client_schemas import check
from gitrepo import AUTHOR, Repo
from runtesting import ADA, ALLOW, INIT, OK, script, theatre
from troupe.core.exit_codes import ExitCode

WRITE = {"writeFile": {"path": "src/a.txt", "content": "two\n"}}


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Repo:
    """A committed git theatre as the working directory, ada acting, the local stage allowed."""
    made = theatre(tmp_path)
    made.write("src/a.txt", "one\n")
    made.commit_all("base")
    for name, value in {**made.env, **ADA, **ALLOW}.items():
        monkeypatch.setenv(name, value)
    monkeypatch.chdir(made.path)
    return made


FAIL = {"event": {"type": "result", "status": "error", "reason": "other", "message": "no"}}
RUN_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def performed(repo: Repo) -> tuple[str, str]:
    """Perform a worktree actor that changes src/a.txt and then fails, so its changes reach no
    gate and are pending for accept or discard (spec: gates, "A worktree run that succeeds with
    changes passes a gate"); its run id and perform's standard error."""
    configure(repo, script(INIT, WRITE, FAIL), workspace="worktree", effects={"write": ["**"]})
    repo.commit_all("config")
    code, _, err = cli("perform", "tester")
    assert code == ExitCode.FAILURE, err
    found = RUN_ID.search(err)
    assert found is not None, err
    return found.group(0), err


def test_perform_names_the_worktree_and_says_how_to_settle_the_changes(repo: Repo) -> None:
    run_id, err = performed(repo)
    assert f"works in its own worktree, .troupe/local/worktrees/{run_id}" in err
    short = run_id[:8]
    assert f"`troupe diff {short}`" in err
    assert f"`troupe accept {short}`" in err
    assert f"`troupe discard {short}`" in err


def test_the_diff_on_standard_output_is_the_captured_diff_and_applies_at_the_base(
    repo: Repo, tmp_path: Path
) -> None:
    run_id, _ = performed(repo)
    code, out, _ = cli("diff", run_id[:8])
    assert code == ExitCode.OK
    patch = tmp_path / "run.diff"
    patch.write_bytes(out.encode("utf-8"))
    checked = subprocess.run(
        ["git", "apply", "--check", str(patch)],  # noqa: S607
        cwd=repo.path,
        env={**repo.env, **AUTHOR},
        capture_output=True,
        check=False,
    )
    assert checked.returncode == 0, checked.stderr


def test_the_diff_as_json_validates_against_its_result_schema(repo: Repo) -> None:
    run_id, _ = performed(repo)
    code, out, _ = cli("diff", run_id, "--json")
    assert code == ExitCode.OK
    check(json.loads(out), "diff-result.schema.json")


def test_accept_writes_the_files_and_names_them(repo: Repo) -> None:
    run_id, _ = performed(repo)
    code, out, err = cli("accept", run_id[:8], "--reason", "looks right")
    assert code == ExitCode.OK, err
    assert f"run {run_id} accepted, unstaged:\n  src/a.txt\n" == out
    assert (repo.path / "src" / "a.txt").read_text(encoding="utf-8") == "two\n"


def test_a_rehearsed_accept_exits_would_change_naming_the_files(repo: Repo) -> None:
    run_id, _ = performed(repo)
    code, out, _ = cli("accept", run_id[:8], "--rehearse")
    assert code == ExitCode.WOULD_CHANGE
    assert "would change:\n  src/a.txt" in out
    assert (repo.path / "src" / "a.txt").read_text(encoding="utf-8") == "one\n"


def test_a_conflicting_accept_names_the_files_the_diff_the_worktree_and_troupe_diff(
    repo: Repo,
) -> None:
    run_id, _ = performed(repo)
    repo.write("src/a.txt", "mine\n")
    code, out, err = cli("accept", run_id[:8])
    assert code == ExitCode.FAILURE
    assert out == ""
    assert "src/a.txt" in err
    assert f"troupe diff {run_id[:8]}" in err
    assert f".troupe/local/worktrees/{run_id}" in err


def test_discard_removes_the_worktree_and_says_git_state_stays(repo: Repo) -> None:
    run_id, _ = performed(repo)
    code, out, err = cli("discard", run_id[:8])
    assert code == ExitCode.OK
    assert f"removed .troupe/local/worktrees/{run_id}" in out
    assert "removes files, not git state" in err
    assert not (repo.path / ".troupe" / "local" / "worktrees" / run_id).exists()


def test_a_rehearsed_discard_exits_would_change_and_keeps_the_worktree(repo: Repo) -> None:
    run_id, _ = performed(repo)
    code, out, _ = cli("discard", run_id[:8], "--rehearse")
    assert code == ExitCode.WOULD_CHANGE
    assert f"would remove .troupe/local/worktrees/{run_id}" in out
    assert (repo.path / ".troupe" / "local" / "worktrees" / run_id).is_dir()


def test_discards_help_says_it_doesnt_undo_git_state(repo: Repo) -> None:
    code, out, _ = cli("discard", "--help")
    assert code == ExitCode.OK
    assert "not git state" in out
    assert "hooks" in out


def test_status_shows_the_workspace_and_pending_changes(repo: Repo) -> None:
    run_id, _ = performed(repo)
    code, out, _ = cli("status", run_id[:8])
    assert code == ExitCode.OK
    assert "  workspace: its own worktree at" in out
    assert "  changes: pending (0 added, 1 modified, 0 deleted)" in out
    assert f"  worktree: .troupe/local/worktrees/{run_id}" in out


def test_rehearsing_a_worktree_perform_shows_the_base_and_makes_no_worktree(repo: Repo) -> None:
    configure(repo, script(INIT, OK), workspace="worktree", effects={"write": ["**"]})
    repo.commit_all("config")
    head = repo.git("rev-parse", "HEAD").strip()
    code, out, _ = cli("perform", "tester", "--rehearse")
    assert code == ExitCode.WOULD_CHANGE
    assert f"  workspace: its own worktree, made at {head}" in out
    assert not (repo.path / ".troupe" / "local" / "worktrees").exists()


# Integration: perform, look, accept; perform again, discard (worktree-stage task 8.1)


def test_a_clean_run_is_kept_by_troupe_and_a_waiting_one_rejected_leaving_the_first_kept(
    repo: Repo,
) -> None:
    # Spec: gates, "troupe approves clean changes by itself", "Rejecting a cue removes the
    # worktree"; end to end through the CLI.
    configure(
        repo,
        script(INIT, WRITE, {"writeFile": {"path": "new.txt", "content": "new\n"}}, OK),
        workspace="worktree",
        effects={"write": ["**"]},
    )
    repo.commit_all("config")
    code, out, err = cli("perform", "tester")
    assert code == ExitCode.OK, err
    first = out.split()[1]
    assert (repo.path / "src" / "a.txt").read_text(encoding="utf-8") == "two\n"
    assert (repo.path / "new.txt").read_text(encoding="utf-8") == "new\n"
    code, out, _ = cli("status", first[:8])
    assert "  changes: accepted (1 added, 1 modified, 0 deleted)" in out
    repo.commit_all("the first run's work")

    configure(
        repo,
        script(INIT, {"writeFile": {"path": "src/a.txt", "content": "three\n"}}, OK),
        workspace="worktree",
        effects={"write": ["**"]},
        approvers=["director"],
        name="second.json",
    )
    repo.commit_all("wait for a person")
    code, out, err = cli("perform", "tester")
    assert code == ExitCode.WAITING, err
    second = out.split()[1]
    assert (repo.path / "src" / "a.txt").read_text(encoding="utf-8") == "two\n"
    assert cli("reject", second[:8], "--reason", "not yet")[0] == ExitCode.OK
    assert (repo.path / "src" / "a.txt").read_text(encoding="utf-8") == "two\n"
    assert not (repo.path / ".troupe" / "local" / "worktrees" / first).exists()
    assert not (repo.path / ".troupe" / "local" / "worktrees" / second).exists()
    code, out, _ = cli("status", second[:8])
    assert code == ExitCode.OK
    assert "  changes: rejected" in out
