"""Claude Code's command line, standard input and private files (spec: claude-code-runner;
design D3, D4)."""

import json
import os
import stat
import sys
from pathlib import Path

import pytest

from troupe_runner_claude_code.command import (
    ENGINE_ENVIRONMENT,
    PrivateDirectoryError,
    budget_text,
    build,
    make_private_directory,
)
from troupe_runner_claude_code.options import parse_options

CLAUDE = Path("/opt/claude/bin/claude")
FIXED = [
    str(CLAUDE),
    "-p",
    "--output-format",
    "stream-json",
    "--verbose",
    "--no-session-persistence",
]


def _flag(argv: list[str], name: str) -> str | None:
    return argv[argv.index(name) + 1] if name in argv else None


def test_no_options_give_the_fixed_flags_isolation_and_the_default_budget(tmp_path: Path) -> None:
    launch = build(CLAUDE, parse_options({}), "say hi", None, tmp_path, {})
    assert launch.argv == [
        *FIXED,
        "--setting-sources",
        "",
        "--strict-mcp-config",
        "--max-budget-usd",
        "5",
    ]
    assert list(tmp_path.iterdir()) == []


def test_setting_sources_are_joined_when_set(tmp_path: Path) -> None:
    options = parse_options({"settingSources": ["project", "local"]})
    assert _flag(build(CLAUDE, options, "d", None, tmp_path, {}).argv, "--setting-sources") == (
        "project,local"
    )


@pytest.mark.parametrize(
    ("budget", "text"), [(0.1, "0.1"), (2, "2"), (12.5, "12.5"), (1e-05, "1e-05")]
)
def test_a_budget_in_the_options_is_passed_as_the_shortest_text_that_round_trips(
    tmp_path: Path, budget: float, text: str
) -> None:
    options = parse_options({"maxBudgetUsd": budget})
    assert _flag(build(CLAUDE, options, "d", None, tmp_path, {}).argv, "--max-budget-usd") == text
    assert float(budget_text(budget)) == budget


def test_permission_mode_and_model_are_passed_only_when_set(tmp_path: Path) -> None:
    bare = build(CLAUDE, parse_options({}), "d", None, tmp_path, {}).argv
    assert "--permission-mode" not in bare
    assert "--model" not in bare
    options = parse_options({"permissionMode": "acceptEdits", "model": "claude-haiku-5-5"})
    argv = build(CLAUDE, options, "d", None, tmp_path, {}).argv
    assert _flag(argv, "--permission-mode") == "acceptEdits"
    assert _flag(argv, "--model") == "claude-haiku-5-5"


def test_the_character_goes_in_a_file_appended_to_the_system_prompt(tmp_path: Path) -> None:
    character = "You are a careful tester.\nÜnïcode ✓"
    argv = build(CLAUDE, parse_options({}), "d", character, tmp_path, {}).argv
    path = Path(str(_flag(argv, "--append-system-prompt-file")))
    assert path.parent == tmp_path
    assert path.read_bytes() == character.encode("utf-8")
    assert "--system-prompt-file" not in argv
    assert not any(character in arg for arg in argv)


def test_no_character_gives_no_system_prompt_flag(tmp_path: Path) -> None:
    argv = build(CLAUDE, parse_options({}), "d", None, tmp_path, {}).argv
    assert not any("system-prompt" in arg for arg in argv)


def test_tool_rules_go_in_a_settings_file_and_never_on_the_command_line(tmp_path: Path) -> None:
    options = parse_options(
        {"allowedTools": ["Bash(git status)", "Read"], "disallowedTools": ["WebFetch"]}
    )
    argv = build(CLAUDE, options, "d", None, tmp_path, {}).argv
    path = Path(str(_flag(argv, "--settings")))
    assert path.parent == tmp_path
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "permissions": {"allow": ["Bash(git status)", "Read"], "deny": ["WebFetch"]}
    }
    assert not any(rule in arg for arg in argv for rule in ("Bash(git status)", "WebFetch"))


def test_only_allowed_tools_give_a_settings_file_with_only_allow(tmp_path: Path) -> None:
    argv = build(CLAUDE, parse_options({"allowedTools": ["Read"]}), "d", None, tmp_path, {}).argv
    assert json.loads(Path(str(_flag(argv, "--settings"))).read_text(encoding="utf-8")) == {
        "permissions": {"allow": ["Read"]}
    }


def test_the_direction_is_standard_input_and_in_no_argument(tmp_path: Path) -> None:
    direction = 'say "hi"\nthen stop'
    launch = build(CLAUDE, parse_options({}), direction, None, tmp_path, {})
    assert launch.stdin == direction.encode("utf-8")
    assert not any("hi" in arg or "stop" in arg for arg in launch.argv)


def test_the_environment_is_the_runners_plus_no_updates_or_telemetry(tmp_path: Path) -> None:
    launch = build(CLAUDE, parse_options({}), "d", None, tmp_path, {"PATH": "/bin", "HOME": "/h"})
    assert launch.env == {"PATH": "/bin", "HOME": "/h", **ENGINE_ENVIRONMENT}


def test_the_private_directory_is_outside_the_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    private = make_private_directory(workspace)
    try:
        assert not private.resolve().is_relative_to(workspace.resolve())
        assert private.name.startswith("troupe-claude-code-")
        if sys.platform != "win32":
            assert stat.S_IMODE(private.stat().st_mode) == 0o700
    finally:
        private.rmdir()


def test_a_temporary_directory_inside_the_workspace_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import tempfile

    inside = tmp_path / "tmp"
    inside.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(inside))
    with pytest.raises(PrivateDirectoryError) as caught:
        make_private_directory(tmp_path)
    assert "inside the workspace" in caught.value.problem
    assert list(inside.iterdir()) == []


def test_an_unusable_temporary_directory_is_refused_naming_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import tempfile

    missing = tmp_path / "missing"
    monkeypatch.setattr(tempfile, "tempdir", str(missing))
    with pytest.raises(PrivateDirectoryError) as caught:
        make_private_directory(tmp_path / "workspace")
    assert caught.value.where == str(missing)
    assert os.path.exists(missing) is False
