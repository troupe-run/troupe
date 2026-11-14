"""troupe init on the command line (spec: cli; init-and-audition design D4, D8, D9)."""

import dataclasses
import io
import json
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

import ollama_stand_in
from gitrepo import AUTHOR, Repo, make_repo
from runtesting import ADA
from troupe.cli import init as init_cli
from troupe.cli import main
from troupe.core import audition as auditions
from troupe.core import interim
from troupe.core.audition import LM_STUDIO_AUDITION_MODEL
from troupe.core.audition import OLLAMA_AUDITION_MODEL as OLLAMA_MODEL
from troupe.core.exit_codes import ExitCode
from troupe.core.policy import ALLOW_UNENFORCED_LOCAL_STAGE, env_name
from troupe.core.schemas import INSTALL_PAGE

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
    assert "Its character, the prompt it runs with, is .troupe/actors/lead.md." in out
    code, out, _ = cli("config", "get", "actors.lead.runner")
    assert code == ExitCode.OK
    assert out.strip() == "claude-code"


CHARACTER_SET = "troupe config set actors.lead.character=@<file>"


def test_an_audition_says_to_change_the_character_with_config_set_not_by_editing(
    repo: Repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, out, _ = cli("init", "--audition")
    assert f"To change it, write yours in a file and run: {CHARACTER_SET}" in out
    assert "edit it" not in out
    mine = repo.path / "character.md"
    mine.write_bytes(b"You are terse.\n")  # write_text writes CRLF on Windows
    command = CHARACTER_SET.replace("<file>", mine.name)
    code, _, err = cli(*shlex.split(command)[1:])
    assert code == ExitCode.OK, err
    code, out, _ = cli("config", "get", "actors.lead.character")
    assert out.removesuffix("\n") == "You are terse.\n"  # config get ends its output with a newline
    lead = repo.path / ".troupe" / "actors" / "lead.md"
    assert lead.read_text(encoding="utf-8") == "You are terse.\n"
    repo.git("add", ".troupe")
    repo.git("commit", "-m", "Add a troupe theatre")
    monkeypatch.setenv(ALLOW_VARIABLE, "true")
    code, _, err = cli("perform", "lead", "--rehearse")
    assert code == ExitCode.WOULD_CHANGE, err
    assert "isn't what troupe wrote" not in err


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


def test_the_ollama_audition_says_ollama_must_run_and_names_ollama_pull_with_its_model(
    repo: Repo,
) -> None:
    # Spec: config, "What init prints for it"; cli, "The Ollama runner".
    code, out, _ = cli("init", "--audition", "--runner", "ollama")
    assert code == ExitCode.OK
    assert "Defined the actor lead, with the ollama runner." in out
    lines = _next(out)
    assert (
        f"   # Ollama must be running, with its model pulled: ollama pull {OLLAMA_MODEL}" in lines
    )
    assert "Claude Code must be" not in out
    assert "runner: ollama" in (repo.path / ".troupe" / "actors" / "lead.yaml").read_text(
        encoding="utf-8"
    )


def test_the_ollama_actor_names_the_ollama_runtime_and_its_model_with_no_options(
    repo: Repo,
) -> None:
    # Spec: config, "The Ollama actor's file". The file leaves runtime and model out until #288,
    # so they're read from config, as config get shows them.
    code, _, err = cli("init", "--audition", "--runner", "ollama")
    assert code == ExitCode.OK, err
    code, out, err = cli("config", "get", "actors.lead", "--json")
    assert code == ExitCode.OK, err
    actor = json.loads(out)["value"]
    assert actor["runner"] == "ollama"
    assert actor["runtime"] == "ollama"
    assert actor["model"] == OLLAMA_MODEL
    assert "options" not in actor
    assert "workspace" not in actor
    lead = (repo.path / ".troupe" / "actors" / "lead.yaml").read_text(encoding="utf-8")
    assert "runner: ollama" in lead
    assert "options" not in lead
    assert (repo.path / ".troupe" / "actors" / "lead.md").is_file()
    assert not (repo.path / ".troupe" / "runtimes").exists()


def test_the_lm_studio_audition_says_to_start_lm_studio_and_get_the_model_and_names_the_extra(
    repo: Repo,
) -> None:
    # Spec: config, "What init prints for it"; cli, "The LM Studio runner".
    code, out, err = cli("init", "--audition", "--runner", "lm-studio")
    assert code == ExitCode.OK, err
    assert "Defined the actor lead, with the lm-studio runner." in out
    lines = _next(out)
    assert (
        "   # LM Studio's server must be running (lms server start), with Require Authentication "
        f"off, and its model downloaded: lms get {LM_STUDIO_AUDITION_MODEL}" in lines
    )
    assert any("troupe-run[lm-studio]" in line for line in lines)
    lead = (repo.path / ".troupe" / "actors" / "lead.yaml").read_text(encoding="utf-8")
    assert "runner: lm-studio" in lead
    code, out, err = cli("config", "get", "actors.lead.runtime", "--json")
    assert code == ExitCode.OK, err
    assert json.loads(out)["value"] == "lm-studio"


def test_the_openai_audition_says_which_key_to_set_and_that_a_run_costs_money(
    repo: Repo,
) -> None:
    # Spec: config, "What init prints for it"; cli, "The OpenAI runner".
    code, out, _ = cli("init", "--audition", "--runner", "openai")
    assert code == ExitCode.OK
    assert "Defined the actor lead, with the openai runner." in out
    lines = _next(out)
    assert (
        "   # Set OPENAI_API_KEY to your API key for the openai runtime. A run costs money, "
        "and stops once it has used the actor's budget of 100,000 tokens." in lines
    )
    assert "Claude Code must be" not in out
    # The file names the runner. Its runtime and model are in config (checked in test_init.py);
    # the file leaves them out until #288.
    lead = (repo.path / ".troupe" / "actors" / "lead.yaml").read_text(encoding="utf-8")
    assert "runner: openai" in lead


def test_the_anthropic_audition_says_which_key_to_set_that_a_run_costs_money_and_its_extra(
    repo: Repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Spec: config, "What init prints for it"; cli, "The Anthropic runner".
    monkeypatch.delenv("TROUPE_RUNTIME_ANTHROPIC_CREDENTIAL_ENV", raising=False)
    code, out, err = cli("init", "--audition", "--runner", "anthropic")
    assert code == ExitCode.OK, err
    assert "Defined the actor lead, with the anthropic runner." in out
    lines = _next(out)
    assert (
        "   # Set ANTHROPIC_API_KEY to your API key for the anthropic runtime. A run costs money, "
        "and stops once it has used the actor's budget of 100,000 tokens." in lines
    )
    assert any("troupe-run[anthropic]" in line for line in lines)
    lead = (repo.path / ".troupe" / "actors" / "lead.yaml").read_text(encoding="utf-8")
    assert "runner: anthropic" in lead
    code, out, err = cli("config", "get", "actors.lead.runtime", "--json")
    assert code == ExitCode.OK, err
    assert json.loads(out)["value"] == "anthropic"


def test_the_openai_audition_names_the_key_variable_the_person_chose(
    repo: Repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TROUPE_RUNTIME_OPENAI_CREDENTIAL_ENV", "MY_OPENAI_KEY")
    code, out, _ = cli("init", "--audition", "--runner", "openai")
    assert code == ExitCode.OK
    assert "Set MY_OPENAI_KEY to your API key for the openai runtime." in out


def test_an_openai_key_override_that_isnt_a_variable_is_named_but_never_shown(
    repo: Repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TROUPE_RUNTIME_OPENAI_CREDENTIAL_ENV", "sk-proj-not-a-variable-name")
    code, out, err = cli("init", "--audition", "--runner", "openai")
    assert code == ExitCode.OK
    assert "TROUPE_RUNTIME_OPENAI_CREDENTIAL_ENV isn't the name of a variable" in out
    assert "sk-proj" not in out + err


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
    assert "anthropic, claude-code, lm-studio, ollama, openai, scripted" in err
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


def test_the_printed_steps_of_an_ollama_audition_give_a_successful_run_with_a_stand_in(
    repo: Repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The audition names the built-in ollama runtime, the local Ollama, so the test points it at
    # a stand-in through the person's environment, as a person would for an Ollama elsewhere
    # (ollama-uses-runtime design D6).
    fake = ollama_stand_in._fake()
    model = {"capabilities": ["completion", "tools"]}
    server = fake.FakeOllama(
        [fake.final("Nothing to change.")], fake.Settings(models={OLLAMA_MODEL: model})
    ).start()
    try:
        code, out, _ = cli("init", "--audition", "--runner", "ollama")
        assert code == ExitCode.OK
        commands = [
            line.split(". ", 1)[1] if line[:1].isdigit() else line.strip()
            for line in _next(out)
            if not line.lstrip().startswith("#")
        ]
        add, commit, allow, perform = commands
        monkeypatch.setenv("TROUPE_RUNTIME_OLLAMA_ENDPOINT", server.url)
        _git(repo, *shlex.split(add)[1:])
        _git(repo, *shlex.split(commit)[1:])
        if sys.platform == "win32":
            variable, value = allow.removeprefix("$env:").split(" = ")
            monkeypatch.setenv(variable, value.strip('"'))
        else:
            variable, value = allow.removeprefix("export ").split("=")
            monkeypatch.setenv(variable, value)
        code, out, err = cli(*shlex.split(perform)[1:])
        assert code == ExitCode.OK, err
        assert out.strip().endswith("succeeded")
        assert server.chats()[0]["model"] == OLLAMA_MODEL
    finally:
        server.stop()


# Requirement: An audition on a runner in an extra names the extra (spec: cli; runner-extras D8)


def test_an_audition_on_a_runner_in_an_extra_names_the_extra_in_the_perform_step(
    repo: Repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    # lm-studio, in an extra (#291), stood in for by the scripted runner, so the audition runs
    # offline. Its audition is the scripted one's.
    entry = dataclasses.replace(interim.RUNNERS["scripted"], in_extra=True)
    monkeypatch.setitem(interim.RUNNERS, "lm-studio", entry)
    monkeypatch.setitem(
        auditions.AUDITIONS,
        "lm-studio",
        lambda: {**auditions.AUDITIONS["scripted"](), "runner": "lm-studio"},
    )
    code, out, err = cli("init", "--audition", "--runner", "lm-studio")
    assert code == 0, err
    lines = _next(out)
    perform = next(n for n, line in enumerate(lines) if "troupe perform lead" in line)
    notes = lines[perform + 1 :]
    assert any("troupe-run[lm-studio]" in line and INSTALL_PAGE in line for line in notes), notes


def test_an_audition_on_a_base_runner_mentions_no_extra(repo: Repo) -> None:
    code, out, err = cli("init", "--audition", "--runner", "scripted")
    assert code == 0, err
    assert "troupe-run[" not in out
