"""What test_scripted_runner.py and test_scripted_runner_unit.py share."""

from typing import Any

INIT = {
    "type": "init",
    "runner": {"name": "scripted", "version": "0.0.1"},
    "effects": "checked",
    "tools": ["Write"],
}
OK = {"type": "result", "status": "ok", "message": "done"}


def _events(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [m["params"] for m in messages if m.get("method") == "run/event"]
