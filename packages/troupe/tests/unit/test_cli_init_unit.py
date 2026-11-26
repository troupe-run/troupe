"""troupe init on the command line, run in-process against a stand-in core: the request it sends,
what it prints and its exit code (spec: cli; init-and-audition design D1, D4, D8, D9;
unit-tests-cli-commands-config-init design D1-D3).

Each result is the protocol's InitResult, copied from what the core returned for that request in a
new git repository. Its tests that start a process, open a socket or use a git theatre are in
integration/test_cli_init.py."""

import os
import sys
from pathlib import Path
from typing import Any

import pytest

from cli_core_stand_in import StandIn, stand_in
from troupe.cli import init as init_cli
from troupe.core.client.messages import InitResult, NoticeUpdate
from troupe.core.exit_codes import ExitCode

DIRECTION = "Write AUDITION.md: a short note on what this repository holds, for someone new to it."
COMMIT = {"kind": "commit", "paths": [".troupe"]}
ALLOW = {
    "kind": "allow-local-stage",
    "variable": "TROUPE_POLICY_ALLOW_UNENFORCED_LOCAL_STAGE",
    "value": "true",
}
BARE_FILES = [
    {"path": ".troupe/.gitignore", "action": "write", "reason": "for this change"},
    {"path": ".troupe/.gitattributes", "action": "write", "reason": "for this change"},
]
CHARACTER = {"path": ".troupe/actors/lead.md", "action": "write", "reason": "for this change"}
ACTOR_FILE = {"path": ".troupe/actors/lead.yaml", "action": "write", "reason": "for this change"}
CHANGE = "01M8B9B0ARS08HDZ44K6PPNT8C"
WARMED_UP = {
    "code": "runner.warmed-up",
    "problem": "Prepared the mistralrs runner's engine in 15.9s, so its first run starts quickly.",
    "fix": "Nothing to do.",
    "details": {"runner": "mistralrs", "seconds": 15.9},
}
WARMING_UP = {
    "code": "runner.warming-up",
    "problem": "Preparing the mistralrs runner's engine, if it needs it on this machine, so its "
    "first run starts quickly. Where there's work to do, the first time can take a minute; it "
    "stops after 120s.",
    "fix": "Nothing to do: wait for it.",
    "details": {"runner": "mistralrs"},
}
COMMIT_LINES = [
    "1. git add .troupe",
    "   git commit -m 'Add a troupe theatre'",
    "   # A run works from your latest commit, so commit the theatre first.",
]
ALLOW_NOTE = (
    "   # troupe runs an actor on your machine only when policy allows it. Run this line now, and "
    "add it once to ~/.zshrc or ~/.bashrc: it then applies to every theatre you run."
)
PERFORM_LINE = f"3. troupe perform lead --direction '{DIRECTION}'"
WORKTREE_NOTE = (
    "   # The run works in its own worktree: see what it did with troupe diff, and keep it with "
    "troupe accept."
)


def _bare(*, rehearsed: bool = False) -> InitResult:
    data = {"rehearsed": rehearsed, "files": BARE_FILES, "entries": [], "steps": [], "notices": []}
    return InitResult.from_data(data if rehearsed else {**data, "change": CHANGE})


def _audition(
    runner: str,
    entries: list[dict[str, Any]],
    *,
    extra: str | None = None,
    rehearsed: bool = False,
    character: bool = True,
    notices: tuple[dict[str, Any], ...] = (),
) -> InitResult:
    perform: dict[str, Any] = {
        "kind": "perform",
        "actor": "lead",
        "runner": runner,
        "direction": DIRECTION,
    }
    if extra is not None:
        perform["extra"] = extra
    data: dict[str, Any] = {
        "rehearsed": rehearsed,
        "files": [*BARE_FILES, *([CHARACTER] if character else []), ACTOR_FILE],
        "entries": [*entries, {"path": ["actors", "lead", "runner"], "after": runner}],
        "steps": [COMMIT, ALLOW, perform],
        "notices": list(notices),
        "actor": {"name": "lead", "runner": runner},
    }
    return InitResult.from_data(data if rehearsed else {**data, "change": CHANGE})


def _paid(runner: str, model: str, *, tokens: object = 100000) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = [
        {"path": ["actors", "lead", "model"], "after": model},
        {"path": ["actors", "lead", "options", "maxTotalTokens"], "after": tokens},
        {"path": ["actors", "lead", "options", "maxTurns"], "after": 10},
        {"path": ["actors", "lead", "runtime"], "after": runner},
    ]
    return entries if tokens is not None else [entries[0], *entries[2:]]


@pytest.fixture
def core(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> StandIn:
    monkeypatch.setattr(init_cli, "SHELL", init_cli.POSIX)
    for name in ("TROUPE_RUNTIME_ANTHROPIC_CREDENTIAL_ENV", "TROUPE_RUNTIME_OPENAI_CREDENTIAL_ENV"):
        monkeypatch.delenv(name, raising=False)
    return stand_in(monkeypatch, tmp_path, theatre=False)


def _made(directory: Path, *files: str) -> list[str]:
    return [f"Made a theatre in {directory}: .troupe/", *(f"  wrote {file}" for file in files)]


def test_the_shell_is_powershell_on_windows_and_posix_elsewhere() -> None:
    expected = init_cli.POWERSHELL if sys.platform == "win32" else init_cli.POSIX
    assert init_cli.SHELL is expected


def test_each_shell_sets_a_variable_in_its_own_syntax() -> None:
    assert init_cli.POSIX.allow_line("NAME", "true") == "export NAME=true"
    assert init_cli.POWERSHELL.allow_line("NAME", "true") == '$env:NAME = "true"'
    assert init_cli.POWERSHELL.profile == "your PowerShell profile ($PROFILE)"


def test_runner_without_audition_is_refused_before_the_core_is_called(core: StandIn) -> None:
    ran = core.run("init", "--runner", "ollama")
    assert ran.code == ExitCode.USAGE
    assert ran.err == [
        "troupe: troupe init: --runner names the example actor's runner, so it needs --audition.",
        "  fix: Add --audition, or leave out --runner. Run `troupe init --help` to see the "
        "options.",
    ]
    assert ran.stdout == ""
    assert core.calls == []


def test_a_bare_init_asks_for_no_audition_and_says_what_to_do_next(core: StandIn) -> None:
    core.reply("init", _bare())
    ran = core.run("init")
    assert core.requests == [("init", {})]
    assert ran.code == ExitCode.OK
    assert ran.out == [
        *_made(Path.cwd(), ".troupe/.gitignore", ".troupe/.gitattributes"),
        "Next: commit .troupe/, and define an actor with troupe config set, or run troupe init "
        "--audition in a new repository for a working example.",
    ]
    assert ran.stderr == ""


def test_a_rehearsed_bare_init_says_what_it_would_write_and_nothing_next(core: StandIn) -> None:
    core.reply("init", _bare(rehearsed=True))
    ran = core.run("init", "--rehearse")
    assert core.requests == [("init", {"rehearse": True})]
    assert ran.code == ExitCode.WOULD_CHANGE
    assert ran.out == [
        f"Would make a theatre in {Path.cwd()}: .troupe/",
        "  would write .troupe/.gitignore",
        "  would write .troupe/.gitattributes",
    ]


def test_the_session_is_the_working_directory_with_this_environment(core: StandIn) -> None:
    core.reply("init", _bare())
    core.run("init")
    (call,) = core.calls
    assert call.session.theatre == Path.cwd()
    assert dict(call.session.env) == dict(os.environ)
    assert not call.session.cancel.requested


def test_an_audition_with_claude_code_prints_each_step_to_copy_with_its_notes(
    core: StandIn,
) -> None:
    core.reply("init", _audition("claude-code", []))
    ran = core.run("init", "--audition")
    assert core.requests == [("init", {"audition": {}})]
    assert ran.code == ExitCode.OK
    assert ran.out == [
        *_made(
            Path.cwd(),
            ".troupe/.gitignore",
            ".troupe/.gitattributes",
            ".troupe/actors/lead.md",
            ".troupe/actors/lead.yaml",
        ),
        "Defined the actor lead, with the claude-code runner.",
        "Its character, the prompt it runs with, is .troupe/actors/lead.md. To change it, edit "
        "that file: troupe records your edit with the next command.",
        "",
        "Next:",
        *COMMIT_LINES,
        "2. export TROUPE_POLICY_ALLOW_UNENFORCED_LOCAL_STAGE=true",
        ALLOW_NOTE,
        PERFORM_LINE,
        "   # Claude Code must be installed and logged in.",
        WORKTREE_NOTE,
    ]


def test_the_allow_step_is_phrased_for_powershell_there(
    core: StandIn, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(init_cli, "SHELL", init_cli.POWERSHELL)
    core.reply("init", _audition("claude-code", []))
    ran = core.run("init", "--audition")
    assert '2. $env:TROUPE_POLICY_ALLOW_UNENFORCED_LOCAL_STAGE = "true"' in ran.out
    assert (
        "   # troupe runs an actor on your machine only when policy allows it. Run this line now, "
        "and add it once to your PowerShell profile ($PROFILE): it then applies to every theatre "
        "you run."
    ) in ran.out


def test_a_rehearsed_audition_names_the_actor_and_its_character_but_no_steps(
    core: StandIn,
) -> None:
    core.reply("init", _audition("claude-code", [], rehearsed=True))
    ran = core.run("init", "--audition", "--rehearse")
    assert core.requests == [("init", {"audition": {}, "rehearse": True})]
    assert ran.code == ExitCode.WOULD_CHANGE
    assert ran.out[-3:] == [
        "Would define the actor lead, with the claude-code runner.",
        "Its character, the prompt it runs with, is .troupe/actors/lead.md. To change it, edit "
        "that file: troupe records your edit with the next command.",
        "Rehearsal: nothing was made, written or recorded.",
    ]
    assert ran.out[1] == "  would write .troupe/.gitignore"


def test_an_actor_with_no_character_file_gets_no_line_about_one(core: StandIn) -> None:
    core.reply("init", _audition("scripted", [], character=False))
    ran = core.run("init", "--audition", "--runner", "scripted")
    assert core.requests == [("init", {"audition": {"runner": "scripted"}})]
    assert ran.out[4:7] == [
        "Defined the actor lead, with the scripted runner.",
        "",
        "Next:",
    ]
    assert ran.out[-2:] == [PERFORM_LINE, WORKTREE_NOTE]


def test_ollama_names_the_model_to_pull_and_the_extra_to_install(core: StandIn) -> None:
    model = [{"path": ["actors", "lead", "model"], "after": "qwen3.5:4b"}]
    core.reply("init", _audition("ollama", model, extra="ollama"))
    ran = core.run("init", "--audition", "--runner", "ollama")
    assert ran.out[-4:] == [
        PERFORM_LINE,
        "   # Ollama must be running, with its model pulled: ollama pull qwen3.5:4b",
        "   # The ollama runner comes with troupe-run[ollama]: whoever runs this theatre "
        "elsewhere installs it with the command at https://troupe.run/docs/opening-night/install/.",
        WORKTREE_NOTE,
    ]


def test_ollama_with_no_model_set_says_to_pull_the_actors_model(core: StandIn) -> None:
    another = [{"path": ["actors", "other", "model"], "after": "qwen3.5:4b"}]
    core.reply("init", _audition("ollama", another))
    ran = core.run("init", "--audition", "--runner", "ollama")
    assert ran.out[-2] == "   # Ollama must be running, with the actor's model pulled."


def test_mistralrs_says_how_to_set_its_model_and_shows_its_notices(core: StandIn) -> None:
    core.reply(
        "init",
        _audition("mistralrs", [], extra="mistralrs", notices=(WARMED_UP,)),
        NoticeUpdate.from_data({"kind": "notice", "notice": WARMING_UP}),
    )
    ran = core.run("init", "--audition", "--runner", "mistralrs")
    assert ran.err == [
        f"troupe: {WARMING_UP['problem']}",
        "  fix: Nothing to do: wait for it.",
        f"troupe: {WARMED_UP['problem']}",
        "  fix: Nothing to do.",
    ]
    assert ran.out[-3] == (
        "   # Set TROUPE_RUNTIME_MISTRALRS_MODEL to the absolute path of a GGUF model file that "
        "can call tools, such as Qwen3-0.6B's. The model runs inside the runner, on this machine. "
        "On macOS, install troupe on a uv-managed Python (uv tool install --managed-python ...)."
    )


@pytest.mark.parametrize(
    ("runner", "model", "variable"),
    [
        ("anthropic", "claude-haiku-5-5", "ANTHROPIC_API_KEY"),
        ("openai", "gpt-6-luna", "OPENAI_API_KEY"),
    ],
)
def test_a_paid_runner_names_its_key_and_its_token_budget(
    core: StandIn, runner: str, model: str, variable: str
) -> None:
    core.reply("init", _audition(runner, _paid(runner, model), extra=runner))
    ran = core.run("init", "--audition", "--runner", runner)
    assert ran.out[-3] == (
        f"   # Set {variable} to your API key for the {runner} runtime. A run costs money, and "
        "stops once it has used the actor's budget of 100,000 tokens."
    )


def test_a_paid_runner_with_no_token_budget_just_says_a_run_costs_money(core: StandIn) -> None:
    core.reply("init", _audition("anthropic", _paid("anthropic", "m", tokens=None)))
    ran = core.run("init", "--audition", "--runner", "anthropic")
    assert ran.out[-2] == (
        "   # Set ANTHROPIC_API_KEY to your API key for the anthropic runtime. A run costs money."
    )


def test_a_paid_runner_whose_budget_isnt_a_whole_number_names_no_budget(core: StandIn) -> None:
    core.reply("init", _audition("anthropic", _paid("anthropic", "m", tokens="lots")))
    ran = core.run("init", "--audition", "--runner", "anthropic")
    assert ran.out[-2].endswith("runtime. A run costs money.")


def test_a_paid_runner_on_a_runtime_troupe_doesnt_build_in_names_no_key(core: StandIn) -> None:
    entries = [{"path": ["actors", "lead", "runtime"], "after": "my-proxy"}]
    core.reply("init", _audition("openai", entries))
    ran = core.run("init", "--audition", "--runner", "openai")
    assert ran.out[-2] == "   # A run costs money."


def test_a_paid_runner_with_no_runtime_set_names_no_key(core: StandIn) -> None:
    core.reply("init", _audition("openai", []))
    ran = core.run("init", "--audition", "--runner", "openai")
    assert ran.out[-2] == "   # A run costs money."


def test_the_key_variable_named_by_the_runtimes_override_is_the_one_to_set(
    core: StandIn, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TROUPE_RUNTIME_ANTHROPIC_CREDENTIAL_ENV", "MY_KEY")
    core.reply("init", _audition("anthropic", _paid("anthropic", "m")))
    ran = core.run("init", "--audition", "--runner", "anthropic")
    assert ran.out[-2].startswith(
        "   # Set MY_KEY to your API key for the anthropic runtime. A run costs money"
    )


def test_an_override_that_isnt_a_variables_name_is_named_but_its_value_never_shown(
    core: StandIn, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TROUPE_RUNTIME_ANTHROPIC_CREDENTIAL_ENV", "sk-ant-secret value")
    core.reply("init", _audition("anthropic", _paid("anthropic", "m", tokens=None)))
    ran = core.run("init", "--audition", "--runner", "anthropic")
    assert ran.out[-2] == (
        "   # TROUPE_RUNTIME_ANTHROPIC_CREDENTIAL_ENV isn't the name of a variable, so a run will "
        "be refused: set it to the name of the variable that holds your key, not the key, or "
        "unset it. A run costs money."
    )
    assert "sk-ant-secret" not in ran.stdout + ran.stderr


def test_an_empty_override_falls_back_to_the_built_in_key(
    core: StandIn, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TROUPE_RUNTIME_OPENAI_CREDENTIAL_ENV", "")
    core.reply("init", _audition("openai", _paid("openai", "m", tokens=None)))
    ran = core.run("init", "--audition", "--runner", "openai")
    assert ran.out[-2] == (
        "   # Set OPENAI_API_KEY to your API key for the openai runtime. A run costs money."
    )


def test_the_value_and_option_an_audition_set_are_read_for_its_actor_only() -> None:
    entries: list[dict[str, Any]] = [
        {"path": ["actors", "other", "model"], "after": "not this"},
        {"path": ["actors", "lead", "model"], "after": "this"},
        {"path": ["actors", "lead", "options", "maxTurns"], "after": 10},
        {"path": ["actors", "lead", "options", "maxTurns", "deeper"], "after": 11},
    ]
    assert init_cli._value(entries, "lead", "model") == "this"
    assert init_cli._value(entries, "lead", "runner") is None
    assert init_cli._option(entries, "lead", "maxTurns") == 10
    assert init_cli._option(entries, "other", "maxTurns") is None


def test_the_refusal_names_the_missing_argument_in_its_details() -> None:
    assert init_cli._missing_audition().details == {
        "command": "troupe init",
        "argument": "--audition",
    }


def test_ctrl_c_during_init_asks_the_core_to_cancel_and_prints_nothing_more(
    core: StandIn,
) -> None:
    core.reply("init", _bare(), presses=1)
    ran = core.run("init")
    assert ran.logged == ()  # no error from the Ctrl-C handler
    assert core.calls[0].session.cancel.requested
    assert ran.code == ExitCode.OK
    assert ran.stderr == ""
