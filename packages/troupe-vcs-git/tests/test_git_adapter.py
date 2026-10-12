"""The git adapter, against real repositories (spec: vcs; event-store design D4, D11)."""

import subprocess
import sys
import time
from pathlib import Path

import pytest

from gitrepo import Repo, isolated_environment, make_repo
from troupe.core.commands import narrow_policy
from troupe.core.errors import TroupeError
from troupe.core.vcs import is_committed, load_vcs
from troupe.platform.processes import is_running
from troupe_vcs_git import GitAdapter
from troupe_vcs_git.defaults import GIT_ENVIRONMENT, GIT_REPOSITORY_LOCATION_VARIABLES


def adapter(repo: Repo, **extra_env: str) -> GitAdapter:
    return GitAdapter(repo.path, source={**repo.env, **extra_env})


@pytest.fixture
def repo(tmp_path: Path) -> Repo:
    return make_repo(tmp_path)


def test_it_is_found_by_name_and_reads_the_branch_of_a_fresh_repository(repo: Repo) -> None:
    vcs = load_vcs("git", repo.path)
    assert vcs.name == "git"
    assert adapter(repo).branch() == "main"


def test_a_fresh_repository_has_a_branch_and_no_head(repo: Repo) -> None:
    git = adapter(repo)
    assert git.branch() == "main"
    assert git.head() is None


def test_head_is_the_commit_once_there_is_one(repo: Repo) -> None:
    commit = repo.commit_all()
    assert adapter(repo).head() == commit


def test_a_detached_head_has_no_branch_and_still_has_its_commit(repo: Repo) -> None:
    commit = repo.commit_all()
    repo.git("switch", "-q", "--detach", commit)
    git = adapter(repo)
    assert git.branch() is None
    assert git.head() == commit


def test_staged_and_committed_files_count_as_committed_and_untracked_ones_do_not(
    repo: Repo,
) -> None:
    repo.write(".troupe/events/committed.jsonl", "{}\n")
    repo.commit_all()
    repo.write(".troupe/events/staged.jsonl", "{}\n")
    repo.git("add", ".troupe/events/staged.jsonl")
    repo.write(".troupe/events/untracked.jsonl", "{}\n")
    git = adapter(repo)
    assert git.committed_under(".troupe/events") == {
        ".troupe/events/committed.jsonl",
        ".troupe/events/staged.jsonl",
    }
    assert is_committed(git, ".troupe/events/staged.jsonl")
    assert not is_committed(git, ".troupe/events/untracked.jsonl")


def test_committed_files_are_found_before_the_first_commit_too(repo: Repo) -> None:
    repo.write(".troupe/events/staged.jsonl", "{}\n")
    repo.git("add", "-A")
    assert adapter(repo).committed_under(".troupe/events") == {".troupe/events/staged.jsonl"}


def test_an_unset_user_email_is_no_identity(repo: Repo) -> None:
    assert adapter(repo).configured_identities() == ()


def test_an_empty_user_email_is_no_identity(repo: Repo) -> None:
    repo.git("config", "user.email", "")
    assert adapter(repo).configured_identities() == ()


def test_a_user_email_is_the_identity(repo: Repo) -> None:
    repo.git("config", "user.email", "ada@example.com")
    assert adapter(repo).configured_identities() == ("ada@example.com",)


def test_two_user_emails_in_one_config_are_both_reported_so_the_caller_can_refuse(
    repo: Repo,
) -> None:
    repo.git("config", "user.email", "ada@example.com")
    repo.git("config", "--add", "user.email", "grace@example.com")
    assert adapter(repo).configured_identities() == ("ada@example.com", "grace@example.com")


def test_a_repository_email_overrides_a_global_one_as_git_does(repo: Repo) -> None:
    repo.git("config", "--global", "user.email", "global@example.com")
    repo.git("config", "user.email", "local@example.com")
    assert adapter(repo).configured_identities() == ("local@example.com",)


def test_a_git_failure_is_vcs_failed_naming_the_command(tmp_path: Path) -> None:
    not_a_repo = tmp_path / "plain"
    not_a_repo.mkdir()
    git = GitAdapter(not_a_repo, source=isolated_environment(tmp_path / "home"))
    with pytest.raises(TroupeError) as caught:
        git.committed_under(".troupe/events")
    assert caught.value.code == "vcs.failed"
    assert "git ls-files" in caught.value.problem


def test_git_missing_from_the_path_is_command_not_found(repo: Repo, tmp_path: Path) -> None:
    empty = tmp_path / "empty-bin"
    empty.mkdir()
    with pytest.raises(TroupeError) as caught:
        adapter(repo, PATH=str(empty)).branch()
    assert caught.value.code == "command.not-found"
    assert "git" in caught.value.problem


def _hanging_git(directory: Path, pid_file: Path) -> None:
    """A stand-in git that starts a child of its own, records the child's id, and never ends."""
    script = directory / "hang.py"
    script.write_text(
        "import subprocess, sys, time\n"
        f"child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        f"open({str(pid_file)!r}, 'w').write(str(child.pid))\n"
        "time.sleep(60)\n",
        encoding="utf-8",
    )
    if sys.platform == "win32":
        (directory / "git.cmd").write_text(f'@"{sys.executable}" "{script}" %*\n', encoding="utf-8")
    else:
        stub = directory / "git"
        stub.write_text(
            f"#!{sys.executable}\nexec(open({str(script)!r}).read())\n", encoding="utf-8"
        )
        stub.chmod(0o755)


def test_a_hung_git_times_out_and_its_whole_tree_is_stopped(repo: Repo, tmp_path: Path) -> None:
    bin_dir = tmp_path / "hang-bin"
    bin_dir.mkdir()
    pid_file = tmp_path / "grandchild.pid"
    _hanging_git(bin_dir, pid_file)
    git = GitAdapter(repo.path, source={**repo.env, "PATH": str(bin_dir)}, timeout=1.0)
    with pytest.raises(TroupeError) as caught:
        git.branch()
    assert caught.value.code == "command.timeout"
    assert "git symbolic-ref" in caught.value.details["command"]
    grandchild = int(pid_file.read_text(encoding="utf-8"))
    deadline = time.monotonic() + 5.0
    while is_running(grandchild) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not is_running(grandchild)


# The environment git receives (spec: vcs, "Each adapter declares its environment policy").


def _env_git_sees(git: GitAdapter) -> dict[str, str]:
    """The environment git was given, printed by a shell alias that git itself runs."""
    out = git.git("-c", "alias.troupe-env=!env", "troupe-env").stdout.decode("utf-8")
    return dict(line.split("=", 1) for line in out.splitlines() if "=" in line)


def test_git_finds_the_users_global_configuration_under_home(repo: Repo) -> None:
    repo.git("config", "--global", "user.email", "ada@example.com")
    assert adapter(repo).configured_identities() == ("ada@example.com",)


def test_git_finds_the_users_xdg_configuration(repo: Repo) -> None:
    xdg = Path(repo.env["XDG_CONFIG_HOME"]) / "git"
    xdg.mkdir(parents=True)
    (xdg / "config").write_text("[user]\n\temail = xdg@example.com\n", encoding="utf-8")
    assert adapter(repo).configured_identities() == ("xdg@example.com",)


def test_git_reads_the_theatres_repository_even_inside_another_repositorys_hook(
    repo: Repo, tmp_path: Path
) -> None:
    other = make_repo(tmp_path, "other", branch="elsewhere")
    git = adapter(
        repo,
        GIT_DIR=str(other.path / ".git"),
        GIT_WORK_TREE=str(other.path),
        GIT_INDEX_FILE=str(other.path / ".git" / "index"),
    )
    assert git.branch() == "main"


def test_unrelated_variables_never_reach_git(repo: Repo) -> None:
    unrelated = {"AWS_SECRET_ACCESS_KEY": "not-a-real-key", "GIT_SSH_COMMAND": "ssh -v"}
    seen = _env_git_sees(adapter(repo, **unrelated))
    assert "AWS_SECRET_ACCESS_KEY" not in seen
    assert seen.get("GIT_SSH_COMMAND") == "ssh -v"
    # HOME isn't checked here: on Windows the shell git runs the alias in (Git for Windows' bash)
    # sets its own HOME, so this view can't show it. That git receives HOME is shown by
    # test_git_finds_the_users_global_configuration_under_home.


def test_every_repository_location_variable_the_installed_git_lists_is_excluded() -> None:
    listed = subprocess.run(
        ["git", "rev-parse", "--local-env-vars"],  # noqa: S607 - the installed git, from PATH
        capture_output=True,
        check=True,
        cwd=Path(__file__).parent,
    ).stdout.decode("utf-8")
    names = set(listed.split())
    assert names
    assert names <= GIT_REPOSITORY_LOCATION_VARIABLES
    assert all(GIT_ENVIRONMENT.forbids(name) for name in names)


def test_narrowing_the_git_policy_wider_is_environment_policy_invalid() -> None:
    with pytest.raises(TroupeError) as caught:
        narrow_policy(GIT_ENVIRONMENT, names={"HOME", "AWS_SECRET_ACCESS_KEY"})
    assert caught.value.code == "environment.policy-invalid"


# The branch token (design D4).


def test_the_branch_token_costs_one_git_command_per_adapter_and_none_after(repo: Repo) -> None:
    repo.commit_all()
    git = adapter(repo)
    first = git.branch_token()
    assert git.commands_run == 1
    for _ in range(20):
        assert git.branch_token() == first
    assert git.commands_run == 1


def test_the_branch_token_changes_when_the_branch_is_switched(repo: Repo) -> None:
    repo.commit_all()
    git = adapter(repo)
    before = git.branch_token()
    time.sleep(0.01)
    repo.git("switch", "-q", "-c", "other")
    assert git.branch_token() != before


def test_the_branch_token_changes_on_a_commit(repo: Repo) -> None:
    repo.commit_all()
    git = adapter(repo)
    before = git.branch_token()
    time.sleep(0.01)
    repo.write("x.txt", "x")
    repo.commit_all()
    assert git.branch_token() != before


def test_the_branch_token_works_in_a_linked_worktree(repo: Repo, tmp_path: Path) -> None:
    repo.commit_all()
    linked = tmp_path / "linked"
    repo.git("worktree", "add", "-q", "-b", "side", str(linked))
    git = GitAdapter(linked, source=repo.env)
    before = git.branch_token()
    assert git.branch() == "side"
    time.sleep(0.01)
    subprocess.run(
        ["git", "switch", "-q", "-c", "side2"],  # noqa: S607
        cwd=linked,
        env=repo.env,
        check=True,
    )
    assert git.branch_token() != before
