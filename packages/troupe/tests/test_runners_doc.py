"""docs/runners.md describes the runner contract exactly as the schemas define it."""

import re
from pathlib import Path

import pytest

from runner_schemas import RUNNER_SCHEMAS, load
from troupe.core.errors import CODES
from troupe.core.notices import CODES as NOTICE_CODES
from troupe.core.runners.outcome import Outcome

pytestmark = pytest.mark.docs  # reads docs/ (scripts/check-paths.toml)

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


def test_every_outcome_and_runner_error_code_is_documented() -> None:
    documented = set(re.findall(r"`([a-z.-]+)`", _section("Outcomes")))
    # Codes for perform, status and logs are documented in docs/runs.md (test_runs_doc.py).
    runs_doc = (DOC.parent / "runs.md").read_text(encoding="utf-8")
    elsewhere = set(re.findall(r"^\| `([a-z]+\.[a-z.-]+)` \|", runs_doc, re.M))
    runner_codes = {code for code in CODES if code.split(".")[0] in {"run", "runner"}} - elsewhere
    assert {str(outcome) for outcome in Outcome} <= documented
    assert runner_codes <= documented


def test_every_runner_notice_code_is_documented() -> None:
    runs_doc = (DOC.parent / "runs.md").read_text(encoding="utf-8")
    runner_notices = {code for code in NOTICE_CODES if code.split(".")[0] in {"run", "runner"}}
    assert runner_notices
    assert all(f"`{code}`" in TEXT or f"| `{code}` |" in runs_doc for code in runner_notices)


def test_the_errors_table_lists_exactly_the_contracts_error_codes() -> None:
    schema = load(RUNNER_SCHEMAS / "errors.schema.json")
    codes = {branch["properties"]["code"]["const"] for branch in schema["oneOf"]}
    assert _first_column(_section("Errors")) == codes
