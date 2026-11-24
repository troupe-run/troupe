"""The Claude Code runner takes the runner contract's protocol versions and JSON-RPC error codes
from the plugin SDK (spec: plugin-sdk; runner-sdk design D4). Its event mapping still builds dicts,
so this checks only those constants."""

import ast
from pathlib import Path

from troupe_plugin_sdk import runner as p
from troupe_runner_claude_code import runner

SOURCE = Path(runner.__file__).parent


def test_the_protocol_versions_and_json_rpc_codes_are_the_sdks() -> None:
    assert runner.PROTOCOL_VERSIONS is p.PROTOCOL_VERSIONS
    assert (
        runner.INVALID_REQUEST,
        runner.METHOD_NOT_FOUND,
        runner.INVALID_PARAMS,
        runner.PARSE_ERROR,
        runner.REFUSED,
    ) == (
        p.JSONRPC_INVALID_REQUEST,
        p.JSONRPC_METHOD_NOT_FOUND,
        p.JSONRPC_INVALID_PARAMS,
        p.JSONRPC_PARSE_ERROR,
        p.JSONRPC_REFUSED,
    )


def test_no_module_of_the_scripted_runner_writes_a_json_rpc_error_code_literally() -> None:
    literals = {p.JSONRPC_INVALID_REQUEST, p.JSONRPC_METHOD_NOT_FOUND, p.JSONRPC_INVALID_PARAMS}
    literals |= {p.JSONRPC_PARSE_ERROR, p.JSONRPC_REFUSED}
    found = [
        f"{path.name}:{node.lineno}"
        for path in sorted(SOURCE.glob("*.py"))
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.UnaryOp)
        and isinstance(node.op, ast.USub)
        and isinstance(node.operand, ast.Constant)
        and isinstance(node.operand.value, int)
        and -node.operand.value in literals
    ]
    assert found == []
