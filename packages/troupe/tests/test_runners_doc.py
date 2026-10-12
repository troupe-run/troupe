"""docs/runners.md describes the runner contract exactly as the schemas define it."""

import re
from pathlib import Path

from runner_schemas import RUNNER_SCHEMAS, load

DOC = Path(__file__).resolve().parents[3] / "docs" / "runners.md"
TEXT = DOC.read_text(encoding="utf-8")


def _section(heading: str) -> str:
    match = re.search(rf"^### {re.escape(heading)}\n(.*?)(?=^#{{2,3}} )", TEXT, re.M | re.S)
    assert match is not None, f"docs/runners.md has no section {heading!r}"
    return match.group(1)


def _first_column(section: str) -> set[str]:
    return set(re.findall(r"^\| `([^`]+)` \|", section, re.M))


def test_the_messages_table_lists_exactly_the_methods_in_the_schemas() -> None:
    methods = {
        load(path)["properties"]["method"]["const"]
        for path in RUNNER_SCHEMAS.glob("*.schema.json")
        if "method" in load(path).get("properties", {})
    }
    assert _first_column(_section("Messages")) == methods


def test_the_run_events_table_lists_exactly_the_event_types_in_the_schema() -> None:
    defs = load(RUNNER_SCHEMAS / "run-event.schema.json")["$defs"]
    types = {
        defs[ref["$ref"].rsplit("/", 1)[1]]["properties"]["type"]["const"]
        for ref in [*defs["event"]["oneOf"], {"$ref": "#/$defs/oversized"}]
    }
    assert _first_column(_section("Run events")) == types
