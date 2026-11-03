"""troupe's Delete and Move as an MCP server Claude Code calls, driven over stdio as Claude Code
would (spec: claude-code-runner, "Delete and move effects are troupe's own tools"; declared-effects
design D8)."""

import json
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import Any

from troupe_plugin_sdk.declaration import Declaration
from troupe_plugin_sdk.effects import Effects
from troupe_runner_claude_code.command import build
from troupe_runner_claude_code.effects_server import write_config
from troupe_runner_claude_code.options import parse_options
from troupe_runner_claude_code.permissions import ClaudeCodePermissions

RUN = "0f8fad5b-d9cb-469f-a165-70867728950e"


def _serve(
    tmp_path: Path, effects: Effects, tools: tuple[str, ...], messages: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Start the server for a workspace under ``tmp_path``, send ``messages``, close its input,
    and return what it answered."""
    workspace, scratch = tmp_path / "workspace", tmp_path / "scratch"
    config = tmp_path / "effects.json"
    write_config(
        config,
        run_id=RUN,
        declaration=Declaration(effects, workspace, scratch),
        tools=tools,
        event_max_bytes=65536,
    )
    lines = "".join(json.dumps(m) + "\n" for m in messages).encode()
    completed = subprocess.run(
        [sys.executable, "-m", "troupe_runner_claude_code.effects_server", str(config)],
        input=lines,
        capture_output=True,
        check=True,
        timeout=60,
    )
    return [json.loads(line) for line in completed.stdout.splitlines()]


def _workspace(tmp_path: Path, files: dict[str, bytes]) -> Path:
    workspace = tmp_path / "workspace"
    for relative, data in files.items():
        path = workspace / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    workspace.mkdir(exist_ok=True)
    (tmp_path / "scratch").mkdir()
    return workspace


def _call(id_: int, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": id_,
        "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    }


HANDSHAKE: list[dict[str, Any]] = [
    {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {}},
    },
    {"jsonrpc": "2.0", "method": "notifications/initialized"},
    {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
]


def test_the_server_names_itself_and_lists_only_the_tools_it_offers(tmp_path: Path) -> None:
    _workspace(tmp_path, {})
    initialized, listed = _serve(tmp_path, Effects(delete=("drafts/**",)), ("Delete",), HANDSHAKE)
    assert initialized["result"]["serverInfo"]["name"] == "troupe"
    assert initialized["result"]["protocolVersion"] == "2025-06-18"
    assert [tool["name"] for tool in listed["result"]["tools"]] == ["Delete"]
    assert listed["result"]["tools"][0]["inputSchema"]["additionalProperties"] is False


def test_a_declared_delete_removes_the_file(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path, {"drafts/a.md": b"a"})
    *_, deleted = _serve(
        tmp_path,
        Effects(delete=("drafts/**",)),
        ("Delete",),
        [*HANDSHAKE, _call(3, "Delete", {"file_path": "drafts/a.md"})],
    )
    assert deleted["result"]["isError"] is False
    assert not (workspace / "drafts" / "a.md").exists()


def test_a_move_outside_what_is_declared_is_an_error_naming_the_move_effect(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path, {"drafts/a.md": b"a"})
    *_, moved = _serve(
        tmp_path,
        Effects(move=("drafts/**",)),
        ("Move",),
        [*HANDSHAKE, _call(3, "Move", {"source": "drafts/a.md", "destination": "docs/a.md"})],
    )
    assert moved["result"]["isError"] is True
    assert "move effect" in moved["result"]["content"][0]["text"]
    assert (workspace / "drafts" / "a.md").exists()


def test_a_tool_the_server_doesnt_offer_is_an_error_result(tmp_path: Path) -> None:
    _workspace(tmp_path, {"a.txt": b"a"})
    *_, answered = _serve(
        tmp_path,
        Effects(delete=("**",)),
        ("Delete",),
        [*HANDSHAKE, _call(3, "Write", {"file_path": "a.txt", "content": "x"})],
    )
    assert answered["result"]["isError"] is True
    assert (tmp_path / "workspace" / "a.txt").read_bytes() == b"a"


def test_an_unknown_method_is_a_json_rpc_error(tmp_path: Path) -> None:
    _workspace(tmp_path, {})
    [answered] = _serve(
        tmp_path, Effects(), (), [{"jsonrpc": "2.0", "id": 9, "method": "resources/list"}]
    )
    assert answered["error"]["code"] == -32601


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
