"""The SDK's README agrees with the code: its tools table with the tool definitions, its limits
table with the defaults (runner-sdk task 4.8), and its lost-content example runs as written
(context-event task 2.4)."""

import ast
import re
from dataclasses import fields
from pathlib import Path

from troupe_plugin_sdk import defaults
from troupe_plugin_sdk import runner as p
from troupe_plugin_sdk.defaults import ToolLimits
from troupe_plugin_sdk.tools import Tools

README = Path(__file__).resolve().parents[1] / "README.md"


def _table(heading: str) -> list[list[str]]:
    """The rows of the first table under ``## heading``, each a list of its cells."""
    text = README.read_text(encoding="utf-8")
    section = text.split(f"## {heading}\n", 1)[1].split("\n## ", 1)[0]
    rows = [line for line in section.splitlines() if line.startswith("|")]
    return [[cell.strip() for cell in row.strip("|").split("|")] for row in rows[2:]]


def _names(cell: str) -> list[str]:
    return re.findall(r"`([^`]+)`", cell)


def test_the_tools_table_lists_each_tool_once_in_order_with_exactly_its_input_fields() -> None:
    rows = _table("Tools")
    documented = [(_names(row[0])[0], _names(row[1])) for row in rows]
    defined = [
        (definition.name, list(definition.input_schema["properties"]))
        for definition in Tools.definitions()
    ]
    assert documented == defined


def test_the_limits_table_lists_each_limit_with_its_default() -> None:
    rows = _table("Limits")
    documented = {_names(row[0])[0]: row[1] for row in rows}
    assert list(documented) == [field.name for field in fields(ToolLimits)]
    for name, shown in documented.items():
        value = getattr(defaults, name.upper())
        if shown.endswith(" KiB"):
            assert value == int(shown.removesuffix(" KiB")) * 1024, name
        elif shown.endswith(" MiB"):
            assert value == int(shown.removesuffix(" MiB")) * 1024 * 1024, name
        else:
            assert value == ast.literal_eval(shown), name


def test_the_lost_content_example_runs_as_written_and_sends_a_valid_context_event() -> None:
    text = README.read_text(encoding="utf-8")
    section = text.split("## Lost content\n", 1)[1].split("\n## ", 1)[0]
    code = section.split("```python\n", 1)[1].split("```", 1)[0]
    sent: list[p.RunEvent] = []
    namespace: dict[str, object] = {
        "run_id": "0f8fad5b-d9cb-469f-a165-70867728950e",
        "event_max_bytes": 65536,
        "send": sent.append,
    }
    exec(code, namespace)  # noqa: S102 - the README's own example
    assert [event.to_data() for event in sent] == [
        {
            "runId": "0f8fad5b-d9cb-469f-a165-70867728950e",
            "seq": 1,
            "type": "context",
            "kind": "compacted",
            "by": "engine",
            "message": "The engine summarised the earlier conversation.",
            "tokensBefore": 41000,
        }
    ]
