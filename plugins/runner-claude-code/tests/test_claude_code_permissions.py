"""The actor's declared effects as Claude Code's permission rules (spec: claude-code-runner, "Write
effects become edit rules", "The scratch directory is Claude Code's to use", "Delete and move
effects are troupe's own tools", "What the translation can't cover is said, not hidden" and "A
pattern Claude Code would read differently is refused"; declared-effects design D8)."""

import sys
from collections.abc import Mapping
from pathlib import Path, PurePath, PurePosixPath, PureWindowsPath

import pytest

from troupe_plugin_sdk.declaration import Declaration, posix_absolute
from troupe_plugin_sdk.effects import Effects
from troupe_runner_claude_code.options import parse_options
from troupe_runner_claude_code.permissions import (
    ClaudeCodePermissions,
    EffectsRefusedError,
    Rules,
)

WORKSPACE = PurePosixPath("/w/t")
SCRATCH = PurePosixPath("/s/run")
DENY = ("Edit(//w/t/.git/**)", "Edit(//w/t/.troupe/**)")


def _rules(
    effects: Effects,
    workspace: PurePath = WORKSPACE,
    scratch: PurePath | None = SCRATCH,
    options: Mapping[str, object] | None = None,
) -> Rules:
    permissions = ClaudeCodePermissions(parse_options(options or {}))
    return permissions.translate(Declaration(effects, workspace, scratch))


def test_the_translation_says_it_is_translated() -> None:
    assert ClaudeCodePermissions(parse_options({})).mode == "translated"


def test_a_write_pattern_becomes_an_edit_rule_and_git_and_troupe_are_denied() -> None:
    rules = _rules(Effects(write=("out/**",)), scratch=None)
    assert rules.allow == ("Edit(//w/t/out/**)",)
    assert rules.deny == DENY
    assert rules.mode == "dontAsk"


def test_a_read_only_actor_may_edit_only_its_scratch_directory() -> None:
    rules = _rules(Effects())
    assert rules.allow == ("Edit(//s/run/**)",)
    assert rules.mcp_tools == ()


def test_a_write_pattern_on_windows_is_rooted_at_the_lowercase_drive() -> None:
    rules = _rules(
        Effects(write=("src/*.py",)), PureWindowsPath("C:\\w\\t"), PureWindowsPath("D:\\s")
    )
    assert rules.allow == ("Edit(//c/w/t/src/*.py)", "Edit(//d/s/**)")
    assert rules.deny == ("Edit(//c/w/t/.git/**)", "Edit(//c/w/t/.troupe/**)")


def test_the_scratch_directory_is_a_working_directory_and_the_temporary_one() -> None:
    rules = _rules(Effects())
    native = str(PurePath(SCRATCH))
    assert rules.add_dirs == (native,)
    assert rules.env == {"TMPDIR": native, "TMP": native, "TEMP": native}


def test_options_rules_come_first_and_the_translation_adds_its_own() -> None:
    options = {"allowedTools": ["Read"], "disallowedTools": ["Edit(docs/**)"]}
    rules = _rules(Effects(write=("out/**",)), options=options)
    assert rules.allow == ("Read", "Edit(//w/t/out/**)", "Edit(//s/run/**)")
    assert rules.deny == ("Edit(docs/**)", *DENY)


def test_plan_is_kept_when_the_options_ask_for_it() -> None:
    assert _rules(Effects(), options={"permissionMode": "plan"}).mode == "plan"


@pytest.mark.parametrize(
    ("effects", "tools"),
    [
        (Effects(delete=("drafts/**",)), ("Delete",)),
        (Effects(move=("drafts/**",)), ("Move",)),
        (Effects(delete=("a/*",), move=("b/*",)), ("Delete", "Move")),
        (Effects(write=("**",)), ()),
    ],
)
def test_troupes_tools_are_offered_and_allowed_only_for_what_is_declared(
    effects: Effects, tools: tuple[str, ...]
) -> None:
    rules = _rules(effects)
    assert rules.mcp_tools == tools
    assert [rule for rule in rules.allow if rule.startswith("mcp__")] == [
        f"mcp__troupe__{tool}" for tool in tools
    ]


def test_an_allowed_shell_rule_is_warned_about() -> None:
    rules = _rules(Effects(), options={"allowedTools": ["Bash(uv run pytest *)", "Read"]})
    [warning] = rules.warnings
    assert "'Bash(uv run pytest *)'" in warning
    assert "audit checks the run's changes" in warning


def test_loaded_setting_sources_are_warned_about() -> None:
    rules = _rules(Effects(), options={"settingSources": ["project"]})
    [warning] = rules.warnings
    assert "project settings" in warning
    assert "may allow more than the actor's effects declare" in warning


def test_with_nothing_loaded_or_allowed_there_is_no_warning() -> None:
    assert _rules(Effects(write=("out/**",))).warnings == ()


@pytest.mark.parametrize(
    ("effects", "where", "character"),
    [
        (Effects(write=("app/[id]/page.tsx",)), "effects.write", "["),
        (Effects(write=("a(1).txt",)), "effects.write", "("),
        (Effects(write=("!keep",)), "effects.write", "!"),
    ],
)
def test_a_pattern_claude_code_would_read_differently_is_refused_naming_it(
    effects: Effects, where: str, character: str
) -> None:
    with pytest.raises(EffectsRefusedError) as caught:
        _rules(effects)
    assert caught.value.code == "claude-code.untranslatable-pattern"
    assert caught.value.where == where
    assert repr(character) in caught.value.problem


@pytest.mark.parametrize("workspace", ["/w/my (copy)", "/w/[draft]", "/w/a*"])
def test_a_workspace_path_claude_code_would_read_differently_is_refused(workspace: str) -> None:
    with pytest.raises(EffectsRefusedError) as caught:
        _rules(Effects(), PurePosixPath(workspace))
    assert caught.value.code == "claude-code.untranslatable-pattern"
    assert caught.value.where == "workspace"


def test_delete_and_move_patterns_are_troupes_tools_own_so_any_pattern_is_kept() -> None:
    rules = _rules(Effects(delete=("app/[id]/*",), move=("a(1)/**",)))
    assert rules.mcp_tools == ("Delete", "Move")


@pytest.mark.skipif(sys.platform == "win32", reason="a symbolic link needs a privilege on Windows")
def test_a_workspace_reached_through_a_link_gets_rules_for_both_forms(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    linked = tmp_path / "linked"
    linked.symlink_to(real, target_is_directory=True)
    rules = _rules(Effects(write=("out/**",)), linked, None)
    given, resolved = posix_absolute(linked), posix_absolute(real.resolve())
    assert rules.allow == (f"Edit(/{given}/out/**)", f"Edit(/{resolved}/out/**)")
    assert f"Edit(/{resolved}/.troupe/**)" in rules.deny
    assert f"Edit(/{given}/.git/**)" in rules.deny
