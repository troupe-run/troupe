"""troupe init on the command line (spec: cli; init-and-audition design D4, D8, D9)."""

import io
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

from gitrepo import AUTHOR, Repo, make_repo
from runtesting import ADA
from troupe.cli import init as init_cli
from troupe.cli import main
from troupe.core import audition as auditions
from troupe.core.exit_codes import ExitCode
from troupe.core.policy import ALLOW_UNENFORCED_LOCAL_STAGE, env_name

ALLOW_VARIABLE = env_name(ALLOW_UNENFORCED_LOCAL_STAGE)


def cli(*argv: str) -> tuple[int, str, str]:
    stdout, stderr = io.StringIO(), io.StringIO()
    code = main(list(argv), stdout=stdout, stderr=stderr)
    return code, stdout.getvalue(), stderr.getvalue()


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Repo:
    made = make_repo(tmp_path)
    for name, value in {**made.env, **ADA}.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv(ALLOW_VARIABLE, raising=False)
    monkeypatch.chdir(made.path)
    return made


def _tree(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file() and ".git" not in path.relative_to(root).parts
    }


# Requirement: Init makes a theatre in the current directory


def test_init_prints_the_theatre_and_its_files_and_status_then_finds_it(repo: Repo) -> None:
    code, out, err = cli("init")
    assert code == ExitCode.OK
    assert f"Made a theatre in {repo.path}: .troupe/" in out
    assert "wrote .troupe/.gitignore" in out
    assert "wrote .troupe/.gitattributes" in out
    assert "troupe init --audition" in out
    assert err == ""
    code, _, _ = cli("status")
    assert code == ExitCode.OK


# Requirement: Init refuses where a theatre already exists


def test_init_where_a_theatre_is_exits_1_naming_it(repo: Repo) -> None:
    cli("init")
    code, out, err = cli("init")
    assert code == ExitCode.FAILURE
    assert out == ""
    assert "already a troupe theatre here" in err
    assert str(repo.path) in err


# Requirement: Init with an audition defines a working example actor


def test_an_audition_names_the_actor_its_runner_and_both_files(repo: Repo) -> None:
    code, out, _ = cli("init", "--audition")
    assert code == ExitCode.OK
    assert "Defined the actor lead, with the claude-code runner." in out
    assert "wrote .troupe/actors/lead.yaml" in out
    assert "wrote .troupe/actors/lead.md" in out
    assert "Its character, the prompt it runs with, is .troupe/actors/lead.md: edit it." in out
    code, out, _ = cli("config", "get", "actors.lead.runner")
    assert code == ExitCode.OK
    assert out.strip() == "claude-code"


# Requirement: Init prints the next steps for its audition


def _next(out: str) -> list[str]:
    return out.split("\nNext:\n", 1)[1].splitlines()


def test_the_steps_are_commit_then_the_policy_variable_then_perform(repo: Repo) -> None:
    _, out, _ = cli("init", "--audition")
    lines = _next(out)
    numbered = [line for line in lines if line[:1].isdigit()]
    assert numbered[0] == "1. git add .troupe"
    assert "   git commit -m 'Add a troupe theatre'" in lines
    allow = (
        f'$env:{ALLOW_VARIABLE} = "true"'
        if sys.platform == "win32"
        else f"export {ALLOW_VARIABLE}=true"
    )
    assert numbered[1] == f"2. {allow}"
    perform = shlex.join(["troupe", "perform", "lead", "--direction", auditions.DIRECTION])
    assert numbered[2] == f"3. {perform}"
    assert "   # Claude Code must be installed and logged in." in lines


def _allow_step(out: str) -> list[str]:
    """The allow step's lines: its numbered line and the notes under it."""
    lines = _next(out)
    start = next(n for n, line in enumerate(lines) if ALLOW_VARIABLE in line)
    end = next((n for n in range(start + 1, len(lines)) if lines[n][:1].isdigit()), len(lines))
    return lines[start:end]


def test_the_allow_step_says_to_add_it_to_the_shell_profile_once_on_linux_and_macos(
    repo: Repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(init_cli, "SHELL", init_cli.POSIX)
    _, out, _ = cli("init", "--audition")
    line, *notes = _allow_step(out)
    assert line == f"2. export {ALLOW_VARIABLE}=true"
    note = " ".join(notes)
    assert "~/.zshrc" in note
    assert "~/.bashrc" in note
    assert "once" in note
    assert "every theatre" in note
    assert "each shell" not in note


def test_the_allow_step_on_windows_is_the_env_form_and_names_the_powershell_profile(
    repo: Repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(init_cli, "SHELL", init_cli.POWERSHELL)
    _, out, _ = cli("init", "--audition")
    line, *notes = _allow_step(out)
    assert line == f'2. $env:{ALLOW_VARIABLE} = "true"'
    note = " ".join(notes)
    assert "$PROFILE" in note
    assert "once" in note
    assert "every theatre" in note
    assert "~/.zshrc" not in note


def test_the_shell_is_powershell_on_windows_and_posix_elsewhere() -> None:
    expected = init_cli.POWERSHELL if sys.platform == "win32" else init_cli.POSIX
    assert init_cli.SHELL is expected


def test_no_policy_step_when_policy_already_allows_the_local_stage(
    repo: Repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(ALLOW_VARIABLE, "true")
    _, out, _ = cli("init", "--audition")
    numbered = [line for line in _next(out) if line[:1].isdigit()]
    assert len(numbered) == 2
    assert numbered[0] == "1. git add .troupe"
    assert numbered[1].startswith("2. troupe perform lead --direction ")
    assert ALLOW_VARIABLE not in out


def test_the_scripted_audition_says_nothing_of_claude_code_or_a_character(repo: Repo) -> None:
    _, out, _ = cli("init", "--audition", "--runner", "scripted")
    assert "Defined the actor lead, with the scripted runner." in out
    assert "Claude Code must be" not in out
    assert "lead.md" not in out


# Requirement: Init's audition runner is named with --runner


def test_runner_without_audition_is_a_usage_error_naming_audition_and_makes_nothing(
    repo: Repo,
) -> None:
    code, out, err = cli("init", "--runner", "scripted")
    assert code == ExitCode.USAGE
    assert out == ""
    assert "troupe init" in err
    assert "--audition" in err
    assert not (repo.path / ".troupe").exists()


def test_an_unknown_runner_names_the_runners_troupe_has_and_makes_nothing(repo: Repo) -> None:
    code, _, err = cli("init", "--audition", "--runner", "gemini")
    assert code == ExitCode.FAILURE
    assert "gemini" in err
    assert "claude-code, scripted" in err
    assert not (repo.path / ".troupe").exists()


# Requirement: Init can be rehearsed


@pytest.mark.parametrize("audition", [(), ("--audition",)], ids=["plain", "audition"])
def test_a_rehearsal_exits_3_and_leaves_the_directory_byte_for_byte_unchanged(
    repo: Repo, audition: tuple[str, ...]
) -> None:
    before = _tree(repo.path)
    code, out, _ = cli("init", *audition, "--rehearse")
    assert code == ExitCode.WOULD_CHANGE
    assert "Would make a theatre" in out
    assert "would write .troupe/.gitignore" in out
    assert not (repo.path / ".troupe").exists()
    assert _tree(repo.path) == before


def test_a_rehearsed_audition_shows_the_actor_files_it_would_write(repo: Repo) -> None:
    _, out, _ = cli("init", "--audition", "--rehearse")
    assert "would write .troupe/actors/lead.yaml" in out
    assert "Would define the actor lead, with the claude-code runner." in out
    assert "Rehearsal: nothing was made, written or recorded." in out


def test_rehearsing_where_a_theatre_exists_exits_with_theatre_exists_code(repo: Repo) -> None:
    cli("init")
    code, _, err = cli("init", "--rehearse")
    assert code == ExitCode.FAILURE
    assert "already a troupe theatre here" in err


# Requirement: Global flags are accepted anywhere


def test_the_version_flag_after_init_gives_the_same_result_as_before_it(repo: Repo) -> None:
    assert cli("init", "--version") == cli("--version", "init")
    assert not (repo.path / ".troupe").exists()


# Requirement: Init prints the next steps for its audition, "The printed steps work in an empty
# repository": the issue's offline "done when", as a person would run it.


def _git(repo: Repo, *args: str) -> None:
    subprocess.run(
        ["git", *args],  # noqa: S607 - git from the test environment's PATH
        cwd=repo.path,
        env={**repo.env, **AUTHOR},
        check=True,
        capture_output=True,
    )


def test_the_printed_steps_of_a_scripted_audition_give_a_successful_run_offline(
    repo: Repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    code, out, _ = cli("init", "--audition", "--runner", "scripted")
    assert code == ExitCode.OK
    commands = [
        line.split(". ", 1)[1] if line[:1].isdigit() else line.strip()
        for line in _next(out)
        if not line.lstrip().startswith("#")
    ]
    assert len(commands) == 4  # git add, git commit, the policy variable, perform
    add, commit, allow, perform = commands
    _git(repo, *shlex.split(add)[1:])
    _git(repo, *shlex.split(commit)[1:])
    if sys.platform == "win32":
        variable, value = allow.removeprefix("$env:").split(" = ")
        monkeypatch.setenv(variable, value.strip('"'))
    else:
        variable, value = allow.removeprefix("export ").split("=")
        monkeypatch.setenv(variable, value)
    argv = shlex.split(perform)
    assert argv[:2] == ["troupe", "perform"]
    code, out, err = cli(*argv[1:])
    assert code == ExitCode.OK, err
    assert out.strip().endswith("succeeded")
