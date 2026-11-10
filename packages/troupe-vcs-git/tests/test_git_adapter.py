"""The git adapter, against real repositories (spec: vcs; event-store design D4, D11)."""

import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

import pytest

from gitrepo import Repo, isolated_environment, make_repo, past_the_racy_window
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


HUNG_GIT_TIMEOUT_SECONDS = 5.0
"""Long enough for the stand-in git to start its child before the timeout kills it. On Windows that
is git.cmd, cmd.exe, the venv's launcher, the interpreter, then the child: 1 s missed it in 4 of 65
rounds of the owner's Windows hunt (#100), and the test then read a pid file that didn't exist."""


def _hanging_git(directory: Path, pid_file: Path) -> None:
    """A stand-in git that starts a child of its own, records the child's id, and never ends."""
    script = directory / "hang.py"
    script.write_text(
        "import os, subprocess, sys, time\n"
        f"child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        # Written whole or not at all, so a kill mid-write can't leave a partial pid behind.
        f"open({str(pid_file) + '.tmp'!r}, 'w').write(str(child.pid))\n"
        f"os.replace({str(pid_file) + '.tmp'!r}, {str(pid_file)!r})\n"
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
    git = GitAdapter(
        repo.path, source={**repo.env, "PATH": str(bin_dir)}, timeout=HUNG_GIT_TIMEOUT_SECONDS
    )
    with pytest.raises(TroupeError) as caught:
        git.branch()
    assert caught.value.code == "command.timeout"
    # The first command branch() runs finds the files its token watches (cache-vcs-state D3).
    assert caught.value.details["command"].startswith("git rev-parse --git-common-dir")
    assert pid_file.exists(), (
        f"the stand-in git hadn't started its child within {HUNG_GIT_TIMEOUT_SECONDS} s, so "
        "there was no tree to check: the precondition this test depends on"
    )
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


def test_the_first_branch_token_runs_two_git_commands_and_none_after_while_nothing_moves(
    repo: Repo,
) -> None:
    repo.commit_all()
    git = GitAdapter(repo.path, source=repo.env, now=past_the_racy_window)
    first = git.branch_token()
    # One finds the watched files; one reads HEAD and the branch's full and short names.
    assert git.commands_run == 2
    for _ in range(20):
        assert git.branch_token() == first
    assert git.commands_run == 2


def _reread_cost(repo: Repo, move: Callable[[], object]) -> tuple[GitAdapter, int]:
    """How many git commands reading the branch and HEAD again costs after ``move``."""
    git = GitAdapter(repo.path, source=repo.env, now=past_the_racy_window)
    git.branch_token()
    time.sleep(0.02)  # a timestamp tick, so a rewritten file can't keep its old mtime
    move()
    before = git.commands_run
    git.branch_token()
    return git, git.commands_run - before


def test_a_reread_after_a_commit_on_a_branch_runs_one_git_command(repo: Repo) -> None:
    repo.commit_all()
    git, cost = _reread_cost(repo, lambda: repo.git("commit", "-q", "--allow-empty", "-m", "b"))
    assert cost == 1
    assert (git.branch(), git.head()) == ("main", repo.git("rev-parse", "HEAD").strip())


def test_a_reread_after_detaching_runs_one_git_command(repo: Repo) -> None:
    commit = repo.commit_all()
    git, cost = _reread_cost(repo, lambda: repo.git("switch", "-q", "--detach"))
    assert cost == 1
    assert (git.branch(), git.head()) == (None, commit)


def test_an_orphan_branch_reports_its_name_and_no_commit_in_three_git_commands(repo: Repo) -> None:
    repo.commit_all()
    git, cost = _reread_cost(repo, lambda: repo.git("switch", "-q", "--orphan", "fresh"))
    assert (git.branch(), git.head()) == ("fresh", None)
    assert cost == 3


def test_a_reread_before_the_first_commit_runs_three_git_commands_as_it_always_has(
    repo: Repo,
) -> None:
    git, cost = _reread_cost(repo, lambda: (repo.write("a.txt", "a"), repo.git("add", "a.txt")))
    assert cost == 3
    assert (git.branch(), git.head()) == ("main", None)


def test_an_unborn_head_with_packed_refs_is_read_right_in_four_git_commands(repo: Repo) -> None:
    repo.commit_all()
    repo.git("pack-refs", "--all")
    git, cost = _reread_cost(repo, lambda: repo.git("switch", "-q", "--orphan", "fresh"))
    assert (git.branch(), git.head()) == ("fresh", None)
    assert cost == 4


def test_an_unborn_head_under_reftable_is_read_right_in_four_git_commands(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, refs="reftable")
    git, cost = _reread_cost(repo, lambda: (repo.write("a.txt", "a"), repo.git("add", "a.txt")))
    assert (git.branch(), git.head()) == ("main", None)
    assert cost == 4


@pytest.mark.parametrize(
    "packed",
    [
        pytest.param(False, id="read as unborn first"),
        pytest.param(True, id="after rev-parse fails"),
    ],
)
def test_a_head_git_refuses_to_read_is_vcs_failed_naming_the_command(
    repo: Repo, packed: bool
) -> None:
    repo.commit_all()
    if packed:
        # With packed-refs, the files can't show HEAD is unborn, so the one rev-parse runs first,
        # fails, and the fallback's symbolic-ref then fails too.
        repo.git("pack-refs", "--all")
    (repo.path / ".git" / "HEAD").write_text("ref: refs/heads/a..b\n")
    git = GitAdapter(repo.path, source=repo.env)
    with pytest.raises(TroupeError) as caught:
        git.branch()
    assert caught.value.code == "vcs.failed"
    assert "git symbolic-ref --quiet HEAD" in caught.value.problem
    assert git.commands_run == (3 if packed else 2)  # finding the watched files, then the reads


def test_reading_the_branch_and_head_again_runs_no_command_while_nothing_moves(
    repo: Repo,
) -> None:
    commit = repo.commit_all()
    git = GitAdapter(repo.path, source=repo.env, now=past_the_racy_window)
    assert (git.branch(), git.head()) == ("main", commit)
    after_first = git.commands_run
    for _ in range(20):
        assert (git.branch(), git.head()) == ("main", commit)
    assert git.commands_run == after_first


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


# Whether a directory is in a repository (spec: vcs, "The git adapter's repository is a work tree").


def _outside(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    """A directory no repository holds, with git told not to look above ``tmp_path`` for one, so a
    repository that happens to hold the test's temporary directory can't answer instead."""
    directory = tmp_path / "plain"
    directory.mkdir()
    env = {**isolated_environment(tmp_path / "home"), "GIT_CEILING_DIRECTORIES": str(tmp_path)}
    return directory, env


def test_a_directory_outside_any_repository_is_not_a_repository_and_the_fix_names_git_init(
    tmp_path: Path,
) -> None:
    directory, env = _outside(tmp_path)
    with pytest.raises(TroupeError) as caught:
        GitAdapter(directory, source=env).check_repository()
    error = caught.value
    assert error.code == "vcs.not-a-repository"
    assert error.path == str(directory.absolute())
    assert error.details == {"directory": str(directory.absolute()), "adapter": "git"}
    assert "git init" in error.fix


def test_a_subdirectory_of_a_work_tree_with_no_commits_is_in_a_repository(repo: Repo) -> None:
    app = repo.path / "app"
    app.mkdir()
    GitAdapter(app, source=repo.env).check_repository()


def test_a_repositorys_git_directory_is_not_a_repository(repo: Repo) -> None:
    with pytest.raises(TroupeError) as caught:
        GitAdapter(repo.path / ".git", source=repo.env).check_repository()
    assert caught.value.code == "vcs.not-a-repository"


def test_a_bare_repository_is_not_a_repository(tmp_path: Path) -> None:
    directory, env = _outside(tmp_path)
    subprocess.run(
        ["git", "init", "-q", "--bare", str(directory)],  # noqa: S607 - git from PATH
        env=env,
        check=True,
    )
    with pytest.raises(TroupeError) as caught:
        GitAdapter(directory, source=env).check_repository()
    assert caught.value.code == "vcs.not-a-repository"
