"""troupe's Delete and Move, as an MCP server Claude Code can call (spec: claude-code-runner,
"Delete and move effects are troupe's own tools"; declared-effects design D8).

Claude Code has no tool for deleting or moving a file, only its shell, and a shell rule matches a
command's text, not the paths it touches. So when an actor declares delete or move, the runner
offers troupe's own tools through this server, and each call is carried out by the plugin SDK's
tools, checked against the declaration exactly as in troupe's own runners.

Usage: ``python -m troupe_runner_claude_code.effects_server <config.json>``, as Claude Code starts
it from the MCP config the runner writes. The config, in the runner's private directory, holds the
run id, the workspace, the scratch directory, the effects, the tools to offer and the event limit,
so nothing from config is on a command line. The server speaks MCP's stdio transport: one JSON-RPC
2.0 message per line. Standard library only.
"""

import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any, BinaryIO

from troupe_plugin_sdk import runner as p
from troupe_plugin_sdk.declaration import Declaration
from troupe_plugin_sdk.effects import Effects
from troupe_plugin_sdk.events import EventNumbering
from troupe_plugin_sdk.tools import Tools
from troupe_runner_claude_code import __version__
from troupe_runner_claude_code.options import MCP_SERVER

PROTOCOL_VERSION = "2025-06-18"
"""The MCP version the server answers with when the client names none."""

METHOD_NOT_FOUND = p.JSONRPC_METHOD_NOT_FOUND
INVALID_PARAMS = p.JSONRPC_INVALID_PARAMS
PARSE_ERROR = p.JSONRPC_PARSE_ERROR


def write_config(
    path: Path,
    *,
    run_id: str,
    declaration: Declaration,
    tools: tuple[str, ...],
    event_max_bytes: int,
) -> None:
    """Write the server's config for one run to ``path``."""
    effects = declaration.effects
    data = {
        "runId": run_id,
        "workspace": str(declaration.workspace),
        "scratch": None if declaration.scratch is None else str(declaration.scratch),
        "effects": {
            "write": list(effects.write),
            "delete": list(effects.delete),
            "move": list(effects.move),
        },
        "tools": list(tools),
        "eventMaxBytes": event_max_bytes,
    }
    path.write_bytes(json.dumps(data, ensure_ascii=False).encode("utf-8"))


class Server:
    """One run's server: the SDK's tools for its declaration, offering only ``tools``."""

    def __init__(self, config: Mapping[str, Any]) -> None:
        declared = config["effects"]
        scratch = config.get("scratch")
        self.tools = Tools(
            Path(config["workspace"]),
            Effects(
                write=tuple(declared["write"]),
                delete=tuple(declared["delete"]),
                move=tuple(declared["move"]),
            ),
            scratch=None if scratch is None else Path(scratch),
        )
        self.offered = tuple(config["tools"])
        self.numbering = EventNumbering(config["runId"], int(config["eventMaxBytes"]))
        self.calls = 0

    def answer(self, message: Mapping[str, Any]) -> dict[str, Any] | None:
        """The response to ``message``, or None for a notification."""
        method, id_ = message.get("method"), message.get("id")
        if "id" not in message:
            return None  # notifications/initialized and the like: nothing to answer
        params = message.get("params") or {}
        if method == "initialize":
            requested = params.get("protocolVersion") if isinstance(params, dict) else None
            return _ok(
                id_,
                {
                    "protocolVersion": requested
                    if isinstance(requested, str)
                    else PROTOCOL_VERSION,
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": MCP_SERVER, "version": __version__},
                },
            )
        if method == "ping":
            return _ok(id_, {})
        if method == "tools/list":
            listed = [
                {"name": d.name, "description": d.description, "inputSchema": d.input_schema}
                for d in self.tools.offered()
                if d.name in self.offered
            ]
            return _ok(id_, {"tools": listed})
        if method == "tools/call":
            return self._call(id_, params)
        return _error(id_, METHOD_NOT_FOUND, f"There's no method {method!r}.")

    def _call(self, id_: object, params: object) -> dict[str, Any]:
        if not isinstance(params, dict) or not isinstance(params.get("name"), str):
            return _error(id_, INVALID_PARAMS, "tools/call needs a tool's name.")
        name = params["name"]
        if name not in self.offered:
            text = f"There's no tool named {name!r} here. The tools are {', '.join(self.offered)}."
            return _ok(id_, {"content": [{"type": "text", "text": text}], "isError": True})
        self.calls += 1
        arguments = params.get("arguments", {})
        step = self.tools.run(f"mcp-{self.calls}", name, arguments, self.numbering)
        return _ok(
            id_, {"content": [{"type": "text", "text": step.output}], "isError": step.is_error}
        )


def _ok(id_: object, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": id_, "result": result}


def _error(id_: object, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": message}}


def serve(config: Mapping[str, Any], stdin: BinaryIO, stdout: BinaryIO) -> None:
    """Answer each message on ``stdin`` until it closes."""
    server = Server(config)
    for line in stdin:
        if not line.strip():
            continue
        try:
            message = json.loads(line)
        except ValueError:
            reply: dict[str, Any] | None = _error(None, PARSE_ERROR, "That line isn't JSON.")
        else:
            reply = server.answer(message) if isinstance(message, dict) else None
        if reply is not None:
            stdout.write(json.dumps(reply, ensure_ascii=False).encode("utf-8") + b"\n")
            stdout.flush()


def main() -> None:
    if len(sys.argv) != 2:
        sys.stderr.write("usage: python -m troupe_runner_claude_code.effects_server <config>\n")
        raise SystemExit(2)
    config = json.loads(Path(sys.argv[1]).read_bytes())
    serve(config, sys.stdin.buffer, sys.stdout.buffer)


if __name__ == "__main__":
    main()
