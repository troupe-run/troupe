"""Declaring a delete effect builds Claude Code's command line with an MCP config naming troupe's
effects server, passed with --strict-mcp-config, and allows its Delete tool in the settings
(spec: claude-code-runner, "Delete and move effects are troupe's own tools"; declared-effects
design D8).

Its tests that start a process, open a socket or use a git theatre are in
integration/test_claude_code_effects_server.py."""

import json
import sys
from pathlib import Path, PurePosixPath

from troupe_plugin_sdk.declaration import Declaration
from troupe_plugin_sdk.effects import Effects
from troupe_runner_claude_code.command import build
from troupe_runner_claude_code.options import parse_options
from troupe_runner_claude_code.permissions import ClaudeCodePermissions


def test_declaring_delete_gives_claude_an_mcp_config_naming_the_server(tmp_path: Path) -> None:
    options = parse_options({})
    declaration = Declaration(
        Effects(delete=("drafts/**",)), PurePosixPath("/w/t"), PurePosixPath("/s")
    )
    rules = ClaudeCodePermissions(options).translate(declaration)
    server = [sys.executable, "-m", "troupe_runner_claude_code.effects_server", "/p/effects.json"]
    argv = build(Path("/c/claude"), options, "d", None, tmp_path, {}, rules, server).argv
    config = json.loads((tmp_path / "mcp.json").read_text(encoding="utf-8"))
    assert argv[argv.index("--mcp-config") + 1] == str(tmp_path / "mcp.json")
    assert "--strict-mcp-config" in argv
    assert config == {
        "mcpServers": {"troupe": {"type": "stdio", "command": server[0], "args": server[1:]}}
    }
    settings = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
    assert "mcp__troupe__Delete" in settings["permissions"]["allow"]
